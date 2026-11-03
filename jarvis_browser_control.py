"""JARVIS public-web research through the isolated Chrome debugging profile.

Runs in Ubuntu WSL; uses Windows PowerShell to access Chrome DevTools on
Windows localhost:9222. This controls ONLY a newly created tab in the separate
JARVIS-Chrome profile. It does not automate the Windows desktop, click elements,
fill forms, submit data or execute model-provided JavaScript.

Browser debugging itself is powerful and is NOT a hard security sandbox.
Never sign in to personal accounts in JARVIS-Chrome. Keep port 9222 local.
"""
from __future__ import annotations

import base64
import ipaddress
import json
import re
import socket
import subprocess
import threading
import time
from urllib.parse import quote_plus, urlsplit

_STOP = threading.Event()
_CDP_BASE = 'http://127.0.0.1:9222'
_MAX_PAGES = 3
_MAX_TEXT_PER_PAGE = 4400


def request_stop() -> None:
    """Request cooperative cancellation between browser steps."""
    _STOP.set()


def reset_stop() -> None:
    _STOP.clear()


def _stopped() -> bool:
    return _STOP.is_set()


def validate_web_url(url: str) -> str:
    """Reject non-public destinations before initiating a navigation.

    This is a safety filter, NOT a substitute for network-level isolation.
    Revalidation after navigation detects redirects, but cannot undo a request.
    """
    if not isinstance(url, str) or len(url) > 2048:
        raise ValueError('Only public URLs up to 2048 characters are supported.')
    parsed = urlsplit(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        raise ValueError('Only HTTP(S) pages are permitted.')
    if parsed.username or parsed.password or parsed.port not in (None, 80, 443):
        raise ValueError('Credentials and nonstandard ports are blocked.')
    host = parsed.hostname.lower().rstrip('.')
    if host in {'localhost', 'localhost.localdomain'} or host.endswith(('.local', '.internal', '.localhost', '.test')):
        raise ValueError('Local addresses are blocked.')
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None
    if literal_ip is not None and not literal_ip.is_global:
        raise ValueError('Private or non-public IP addresses are blocked.')
    try:
        records = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f'Could not resolve {host}.') from exc
    if not records or any(not ipaddress.ip_address(info[4][0]).is_global for info in records):
        raise ValueError('Private or non-public network addresses are blocked.')
    return url


def _ps_run(script: str, *, timeout: int = 35) -> object:
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    try:
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
            capture_output=True, timeout=timeout, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError('Could not reach the Windows Chrome debugging service.') from exc
    stdout = result.stdout.decode('utf-8-sig', errors='replace').strip()
    stderr = result.stderr.decode('utf-8-sig', errors='replace').strip()
    if result.returncode:
        raise RuntimeError('Windows Chrome control failed: ' + (stderr or stdout)[-850:])
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError('Unexpected Chrome bridge response: ' + stdout[:200]) from exc


def _new_research_tab() -> str:
    """Create a blank tab in the already-running dedicated Chrome instance."""
    script = r'''
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$tab = Invoke-RestMethod -Method Put -Uri 'http://127.0.0.1:9222/json/new?about:blank' -TimeoutSec 8
if (!$tab.id -or $tab.type -ne 'page') { throw 'Could not create a JARVIS research tab.' }
@{id=[string]$tab.id} | ConvertTo-Json -Compress
'''
    result = _ps_run(script, timeout=18)
    if not isinstance(result, dict) or not isinstance(result.get('id'), str):
        raise RuntimeError('Chrome did not return a research tab ID.')
    return result['id']


def _cdp(tab_id: str, method: str, params: dict, *, timeout: int = 32) -> dict:
    """Send one fixed CDP command to the tab created by this research task."""
    if method not in {'Page.navigate', 'Runtime.evaluate'}:
        raise ValueError('Unsupported Chrome action.')
    if not isinstance(tab_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{6,100}', tab_id):
        raise ValueError('Invalid Chrome tab ID.')
    command = {'id': 1, 'method': method, 'params': params}
    b64 = base64.b64encode(json.dumps(command).encode('utf-8')).decode('ascii')
    ps = r'''
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$targetId = 'TAB_ID_PLACEHOLDER'
$cmd = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('COMMAND_PLACEHOLDER'))
$raw = (Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:9222/json/list' -TimeoutSec 6).Content
$tabs = ConvertFrom-Json -InputObject $raw
$tab = $null
foreach ($entry in $tabs) {
    if ($entry.type -eq 'page' -and $entry.id -eq $targetId) { $tab = $entry; break }
}
if (!$tab) { throw 'JARVIS research tab has been closed.' }
$ws = [System.Uri]::new([string]$tab.webSocketDebuggerUrl)
$client = [System.Net.WebSockets.ClientWebSocket]::new()
$cts = [System.Threading.CancellationTokenSource]::new([System.TimeSpan]::FromSeconds(20))
try {
    [void]$client.ConnectAsync($ws, $cts.Token).GetAwaiter().GetResult()
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($cmd)
    [void]$client.SendAsync([System.ArraySegment[byte]]::new($bytes),
        [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $cts.Token).GetAwaiter().GetResult()
    [byte[]]$buffer = New-Object byte[] 16384
    for ($i=0; $i -lt 30; $i++) {
        $builder = [System.Text.StringBuilder]::new()
        do {
            $part = $client.ReceiveAsync([System.ArraySegment[byte]]::new($buffer),
                $cts.Token).GetAwaiter().GetResult()
            if ($part.MessageType -eq [System.Net.WebSockets.WebSocketMessageType]::Close) {
                throw 'Chrome closed the debugging connection.'
            }
            [void]$builder.Append([System.Text.Encoding]::UTF8.GetString($buffer, 0, $part.Count))
            if ($builder.Length -gt 150000) { throw 'Chrome response too large.' }
        } while (!$part.EndOfMessage)
        $reply = $builder.ToString() | ConvertFrom-Json
        if ($reply.id -ne 1) { continue }
        if ($reply.error) { throw ('CDP error: ' + $reply.error.message) }
        $reply.result | ConvertTo-Json -Compress -Depth 20
        exit 0
    }
    throw 'Chrome did not return the matching response.'
}
finally { $client.Dispose(); $cts.Dispose() }
'''.replace('TAB_ID_PLACEHOLDER', tab_id).replace('COMMAND_PLACEHOLDER', b64)
    output = _ps_run(ps, timeout=timeout)
    if not isinstance(output, dict):
        raise RuntimeError('Chrome did not return a structured response.')
    return output


# The JavaScript below is FIXED by this application, never composed from webpage
# text or model commands. It reads page content and visible search-result links.
# JARVIS_RESEARCH_RELIABILITY_V2: prefer the main article over navigation menus.
_SNAPSHOT_JS = r'''(() => {
    const main = document.querySelector('main, article, [role="main"], #main-content, #content');
    const root = main || document.body;
    let text = '';
    if (root) {
      const copy = root.cloneNode(true);
      copy.querySelectorAll('nav, footer, header, aside, script, style, [role="navigation"]').forEach(e => e.remove());
      text = (copy.innerText || copy.textContent || '').slice(0, 11000);
      if (!text.trim()) text = (root.innerText || '').slice(0, 11000);
    }
    return {
      title: document.title,
      url: location.href,
      text,
      links: [...document.querySelectorAll('a')]
        .filter(a => a.querySelector('h3') && a.href && a.href.startsWith('http'))
        .slice(0, 24)
        .map(a => ({title:(a.querySelector('h3')?.innerText || a.innerText || '').slice(0,160), url:a.href}))
    };
})()'''

def _snapshot(tab_id: str) -> dict:
    output = _cdp(tab_id, 'Runtime.evaluate', {'expression': _SNAPSHOT_JS, 'returnByValue': True, 'silent': True})
    result = output.get('result', {})
    if output.get('exceptionDetails') or not isinstance(result, dict):
        raise RuntimeError('Chrome could not inspect the loaded page.')
    value = result.get('value')
    if not isinstance(value, dict) or not all(isinstance(value.get(k), str) for k in ('url', 'title', 'text')):
        raise RuntimeError('Chrome did not return page content.')
    return value


def _navigate(tab_id: str, url: str) -> dict:
    validate_web_url(url)
    try:
        previous_url = _snapshot(tab_id)['url']
    except RuntimeError:
        previous_url = ''
    output = _cdp(tab_id, 'Page.navigate', {'url': url})
    if output.get('errorText'):
        raise RuntimeError('Chrome navigation failed: ' + str(output['errorText']))
    if output.get('isDownload'):
        raise RuntimeError('The URL attempted to initiate a download; research stopped for this page.')
    # Page.navigate returns before scripts and DOM are always ready.
    for _ in range(5):
        if _stopped():
            raise RuntimeError('Research stopped by user.')
        time.sleep(1.2)
        snapshot = _snapshot(tab_id)
        actual = snapshot['url']
        if actual in {'about:blank', ''} or (actual == previous_url and actual != url):
            continue
        try:
            validate_web_url(actual)
        except ValueError as exc:
            raise RuntimeError('Chrome redirected to a blocked address; refusing to read content.') from exc
        if snapshot['text'].strip():
            return snapshot
    raise RuntimeError('Page did not provide readable text.')


# JARVIS_RESEARCH_RELIABILITY_V2: rank result links, skip blocked pages,
# and retry an alternate scholarly search when the initial results are weak.
def _academic_query(query: str) -> bool:
    return bool(re.search(r'\b(stud(?:y|ies)|papers?|academic|scientific|peer.review|journal|conference)\b', query, re.I))


def _blocked_page(snapshot: dict) -> bool:
    title = snapshot.get('title', '').strip().lower()
    body = snapshot.get('text', '')[:700].lower()
    return (
        any(key in title for key in ('just a moment', 'attention required', 'access denied', 'captcha', 'verify you are human'))
        or any(key in body for key in ('checking your browser before accessing', 'verify you are human',
                                      'please enable javascript and cookies to continue',
                                      'sorry, you have been blocked'))
    )


def _pick_links(snapshot: dict, max_pages: int, *, academic: bool = False) -> list[dict]:
    choices = []
    seen = set()
    for position, link in enumerate(snapshot.get('links', [])):
        if not isinstance(link, dict):
            continue
        url, title = link.get('url', ''), link.get('title', '')
        if not isinstance(url, str) or not isinstance(title, str) or not title.strip():
            continue
        host = (urlsplit(url).hostname or '').lower()
        if host == 'google.com' or host.endswith('.google.com') or host.endswith('.googleusercontent.com'):
            continue
        if url in seen:
            continue
        # Market forecasts are not academic experiments or peer-reviewed papers.
        if academic and re.search(r'\b(market|forecast|pricing|market size|market share)\b', title, re.I):
            continue
        try:
            validate_web_url(url)
        except ValueError:
            continue
        seen.add(url)
        score = 0
        if academic:
            if any(host == domain or host.endswith('.' + domain) for domain in
                   ('arxiv.org', 'acm.org', 'ieee.org', 'usenix.org', 'springer.com',
                    'sciencedirect.com', 'nature.com', 'doi.org')) or host.endswith('.edu'):
                score += 4
            if re.search(r'\b(study|empirical|testing|test|research|journal|conference|paper)\b', title, re.I):
                score += 2
            if 'researchgate.net' in host:
                score -= 2  # Often shows verification pages to automation.
        choices.append((score, position, {'url': url, 'title': title[:130]}))
    choices.sort(key=lambda x: (-x[0], x[1]))
    return [item for _, _, item in choices[:max_pages]]


def research_public_web(query: str, *, max_pages: int = 3) -> dict:
    """Research public pages using only the JARVIS Chrome tab.

    Try up to two searches and eight page navigations; only retain readable
    pages. This does not click, fill forms, or use Windows keyboard/mouse.
    """
    if not isinstance(query, str) or not (2 <= len(query.strip()) <= 220):
        raise ValueError('Research query must be 2–220 characters.')
    if not isinstance(max_pages, int) or isinstance(max_pages, bool) or not 1 <= max_pages <= _MAX_PAGES:
        raise ValueError('Maximum pages must be 1–3.')
    reset_stop()
    tab_id = _new_research_tab()
    academic = _academic_query(query)
    base_query = query.strip()
    queries = [base_query]
    if academic:
        queries.append(base_query + ' research paper -market -forecast')
    else:
        queries.append(base_query + ' -market -forecast')
    pages, errors, seen_urls = [], [], set()
    attempted = 0
    search_url = ''
    for round_index, current_query in enumerate(queries):
        if _stopped() or len(pages) >= max_pages or attempted >= 8:
            break
        # No second search if the first one already produced sufficient evidence.
        if round_index > 0 and len(pages) >= min(2, max_pages):
            break
        current_search_url = 'https://www.google.com/search?q=' + quote_plus(current_query)
        if not search_url:
            search_url = current_search_url
        print('[JARVIS BROWSER] Searching in isolated Chrome:', current_query, flush=True)
        try:
            snapshot = _navigate(tab_id, current_search_url)
            if _blocked_page(snapshot):
                errors.append('Search results displayed a verification page.')
                continue
            candidates = _pick_links(snapshot, 12, academic=academic)
            if not candidates:
                errors.append('Search engine exposed no usable result links.')
                continue
        except (RuntimeError, ValueError, OSError) as exc:
            errors.append('Search failed: ' + str(exc)[:180])
            continue
        for item in candidates:
            if _stopped() or len(pages) >= max_pages or attempted >= 8:
                break
            if item['url'] in seen_urls:
                continue
            seen_urls.add(item['url'])
            attempted += 1
            try:
                data = _navigate(tab_id, item['url'])
                if _blocked_page(data):
                    errors.append(item['url'] + ': verification or access-block page')
                    continue
                text = data['text'].strip()
                if len(text) < 250:
                    errors.append(item['url'] + ': too little readable article content')
                    continue
                if academic and re.search(r'\b(market forecast|market size|industry forecast|market research report)\b',
                                          data['title'], re.I):
                    errors.append(item['url'] + ': market analysis, not an academic study')
                    continue
                pages.append({'title': data['title'][:180], 'url': data['url'],
                              'text': text[:_MAX_TEXT_PER_PAGE]})
                print('[JARVIS BROWSER] Read:', data['url'], flush=True)
            except (RuntimeError, ValueError, OSError) as exc:
                errors.append(item['url'] + ': ' + str(exc)[:180])
    return {'query': base_query, 'stopped': _stopped(), 'pages': pages,
            'errors': errors[:12], 'search_url': search_url}


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python jarvis_browser_control.py "Python language documentation"')
    try:
        report = research_public_web(' '.join(sys.argv[1:]), max_pages=2)
        print(json.dumps({'query': report['query'], 'pages': [
            {'title': p['title'], 'url': p['url'], 'preview': p['text'][:300]}
            for p in report['pages']], 'errors': report['errors'], 'stopped': report['stopped']}, indent=2))
    except (ValueError, RuntimeError) as error:
        raise SystemExit('JARVIS Chrome research failed: ' + str(error))
