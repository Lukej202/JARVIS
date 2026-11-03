"""Read visible text from an already-open tab in JARVIS's separate Chrome profile.

Windows Chrome must be running with remote debugging bound to 127.0.0.1:9222.
WSL communicates through a Windows PowerShell subprocess, because the debugging
socket is reachable on Windows localhost, not necessarily on WSL localhost.

This module *only reads an explicitly named open HTTP(S) tab*. It does not launch
browsers, navigate, click, authenticate, or evaluate model-authored JavaScript.
Keep Chrome's debugging profile separate from your personal Chrome profile.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from urllib.parse import urlsplit


def read_open_chrome_tab(url: str, *, timeout: int = 30) -> dict[str, str]:
    """Return {title, url, text} for an exact-URL tab already open in JARVIS Chrome.

    Uses fixed, read-only DOM JavaScript. Browser debugging can otherwise grant
    broad control, so this should only run against the dedicated JARVIS profile.
    """
    if not isinstance(url, str) or len(url) > 2048:
        raise ValueError("Provide one HTTP(S) webpage URL, at most 2048 characters.")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only ordinary HTTP(S) webpage URLs are supported.")

    encoded_url = base64.b64encode(url.encode("utf-8")).decode("ascii")
    # All external inputs enter through strictly base64-encoded string literals;
    # JavaScript and the CDP method are fixed, not supplied by the AI model.
    ps = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$requestedUrl = [System.Text.Encoding]::UTF8.GetString(
    [System.Convert]::FromBase64String('URL_BASE64_HERE'))
# Fetch the raw JSON and parse it once. PowerShell can otherwise treat the
# JSON array as a nested array, yielding multiple WebSocket addresses.
$tabsJson = (Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:9222/json/list' -TimeoutSec 6).Content
$tabs = ConvertFrom-Json -InputObject $tabsJson
$tab = $null
foreach ($candidate in $tabs) {
    if ($candidate.type -eq 'page' -and $candidate.url -eq $requestedUrl) {
        $tab = $candidate
        break
    }
}
if ($null -eq $tab) {
    throw "No tab with that exact URL is open in the JARVIS Chrome debugging profile: $requestedUrl"
}
$wsUrl = $tab.webSocketDebuggerUrl
if ($wsUrl -isnot [string] -or [string]::IsNullOrWhiteSpace($wsUrl)) {
    throw "Chrome returned an invalid WebSocket address for the selected tab."
}
$wsUri = [System.Uri]::new($wsUrl)

$socket = [System.Net.WebSockets.ClientWebSocket]::new()
$cts = [System.Threading.CancellationTokenSource]::new(
    [System.TimeSpan]::FromSeconds(15))
try {
    [void]$socket.ConnectAsync($wsUri, $cts.Token).GetAwaiter().GetResult()
    $fixedExpression = '({title: document.title, url: location.href, text: document.body ? document.body.innerText.slice(0, 12000) : ""})'
    $command = @{
        id = 1
        method = 'Runtime.evaluate'
        params = @{
            expression = $fixedExpression
            returnByValue = $true
            silent = $true
        }
    } | ConvertTo-Json -Depth 6 -Compress
    [byte[]]$bytes = [System.Text.Encoding]::UTF8.GetBytes($command)
    $segment = [System.ArraySegment[byte]]::new($bytes)
    [void]$socket.SendAsync($segment, [System.Net.WebSockets.WebSocketMessageType]::Text,
        $true, $cts.Token).GetAwaiter().GetResult()

    [byte[]]$buffer = New-Object byte[] 16384
    for ($i = 0; $i -lt 30; $i++) {
        $builder = [System.Text.StringBuilder]::new()
        do {
            $part = $socket.ReceiveAsync([System.ArraySegment[byte]]::new($buffer),
                $cts.Token).GetAwaiter().GetResult()
            if ($part.MessageType -eq [System.Net.WebSockets.WebSocketMessageType]::Close) {
                throw 'Chrome closed the debugging connection before sending the result.'
            }
            [void]$builder.Append([System.Text.Encoding]::UTF8.GetString(
                $buffer, 0, $part.Count))
            if ($builder.Length -gt 100000) {
                throw 'Chrome debugging reply exceeded the 100 KB safety limit.'
            }
        } while (-not $part.EndOfMessage)

        $reply = $builder.ToString() | ConvertFrom-Json
        if ($reply.id -ne 1) { continue }  # Ignore asynchronous DevTools events.
        if ($reply.error) { throw "Chrome CDP error: $($reply.error.message)" }
        if ($reply.result.exceptionDetails) { throw 'Page text extraction raised an exception.' }
        if (-not $reply.result.result) { throw 'Chrome returned no page-text result.' }
        $reply.result.result.value | ConvertTo-Json -Depth 4 -Compress
        exit 0
    }
    throw 'Could not find the matching page-text response from Chrome.'
}
finally {
    $socket.Dispose()
    $cts.Dispose()
}
'''.replace("URL_BASE64_HERE", encoded_url)

    encoded_script = base64.b64encode(ps.encode("utf-16le")).decode("ascii")
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_script],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Windows PowerShell is unavailable from this WSL terminal.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Timed out waiting for the JARVIS Chrome debugging interface.") from exc

    stdout = completed.stdout.decode("utf-8-sig", errors="replace").strip()
    stderr = completed.stderr.decode("utf-8-sig", errors="replace").strip()
    if completed.returncode != 0:
        raise RuntimeError((stderr or stdout or "PowerShell Chrome reader failed")[-1200:])

    # Error messages printed to stdout would cause parsing to fail rather than
    # silently becoming plausible webpage content.
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Unexpected response from Chrome reader: {stdout[:350]}") from exc
    if not isinstance(result, dict) or not all(isinstance(result.get(k), str) for k in ("title", "url", "text")):
        raise RuntimeError("Chrome returned an unexpected page object.")
    if result["url"] != url:
        raise RuntimeError("The Chrome tab navigated while being read; no content returned.")
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python jarvis_browser.py https://www.python.org/about/")
    try:
        page = read_open_chrome_tab(sys.argv[1])
        print(f"Title: {page['title']}\nURL: {page['url']}\n\nVisible text:\n{page['text'][:1200]}")
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(f"Chrome reader failed: {exc}")
