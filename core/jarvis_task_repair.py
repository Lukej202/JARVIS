"""Bounded compiler-diagnostic Verilog repair proposals. Never changes files or runs programs."""
import json
import re
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class RepairError(ValueError):
    pass


def _target_from_diagnostics(diagnostics, sources):
    candidates = []
    for name in sources:
        basename = re.escape(name.rsplit('/', 1)[-1])
        hits = re.findall(r'(?m)(?:^|[/\s])' + basename + r':\d+', diagnostics)
        if hits:
            candidates.append((len(hits), name))
    if not candidates:
        raise RepairError('Compiler diagnostics did not identify a project source file.')
    return max(candidates)[1]


def _simple_missing_finish_semicolon(target, diagnostics, source):
    """Conservative, syntax-only fallback for the exact missing $finish; fixture.

    Require an actual syntax error reported near the affected line. Never alter
    multiple statements, an unrelated file, or a valid $finish statement.
    """
    if not re.search(r'(?i)syntax error|malformed statement', diagnostics):
        return None
    base = re.escape(target.rsplit('/', 1)[-1])
    error_lines = [int(n) for n in re.findall(r'(?:^|[/\s])' + base + r':(\d+):\s*(?:syntax error|error: Malformed statement)', diagnostics, re.M | re.I)]
    if not error_lines:
        return None
    lines = source.splitlines(keepends=True)
    matches = []
    for index, line in enumerate(lines):
        # Only a standalone `$finish` followed immediately by `end` (with optional
        # whitespace), not a comment or a more complex expression.
        if not re.fullmatch(r'[ \t]*\$finish[ \t]*(?:\r?\n)?', line):
            continue
        if index + 1 >= len(lines) or not re.fullmatch(r'[ \t]*end[ \t]*(?:\r?\n)?', lines[index + 1]):
            continue
        if any(abs(error_line - (index + 1)) <= 3 for error_line in error_lines):
            matches.append(index)
    if len(matches) != 1:
        return None
    index = matches[0]
    newline = '\r\n' if lines[index].endswith('\r\n') else '\n' if lines[index].endswith('\n') else ''
    lines[index] = lines[index].rstrip('\r\n').rstrip(' \t') + ';' + newline
    return ''.join(lines)


def _model_repair(objective, diagnostics, sources, target, model, base_url, attempt):
    system = (
        'Fix one Verilog file after an Icarus Verilog compilation failure. '
        'Reply with exactly one JSON object {"filename":"<exact target>","content":"<complete corrected file>"}. '
        'The filename must equal the target string exactly. Preserve all design behavior, '
        'module names, interfaces, and functional checks. Fix the stated compilation error only. '
        'Return a CHANGED version of the target file, with no markdown or other files.'
    )
    if attempt:
        system += (' Your previous answer was invalid or unchanged. Diagnose the compiler line numbers '
                   'carefully and make a minimal concrete syntax correction; do not repeat the original file.')
    prompt = json.dumps({'objective': str(objective)[:700], 'target': target,
                         'compiler_diagnostics': str(diagnostics)[:3800],
                         'existing_sources': sources}, ensure_ascii=False)
    payload = {'model': model,
               'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}],
               'stream': False, 'think': False, 'format': 'json',
               'options': {'num_predict': 3000, 'temperature': 0}}
    req = Request(base_url.rstrip('/') + '/api/chat', data=json.dumps(payload).encode(),
                  headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urlopen(req, timeout=180) as response:
            data = json.load(response)
    except HTTPError as exc:
        detail = exc.read(500).decode('utf-8', errors='replace')
        raise RepairError(f'Ollama HTTP {exc.code}: {detail}') from exc
    except Exception as exc:
        raise RepairError(f'Ollama repair request failed: {type(exc).__name__}: {exc}') from exc
    if data.get('done_reason') == 'length':
        raise RepairError('Model ran out of repair tokens.')
    try:
        result = json.loads((data.get('message') or {}).get('content') or '')
    except (TypeError, ValueError) as exc:
        raise RepairError('Model returned invalid repair JSON.') from exc
    if not isinstance(result, dict):
        raise RepairError('Model returned a non-object repair.')
    if result.get('filename') != target:
        raise RepairError('Model attempted to repair a different file.')
    content = result.get('content')
    if not isinstance(content, str) or not content.strip() or len(content) > 10000:
        raise RepairError('Model returned an invalid or oversized source replacement.')
    if not re.search(r'\bmodule\s+[A-Za-z_]\w*', content):
        raise RepairError('Proposed source has no Verilog module declaration.')
    if content == sources[target]:
        raise RepairError('Model returned unchanged source.')
    return content


def propose_verilog_repair(objective, diagnostics, sources, model, base_url):
    if not isinstance(sources, dict) or len(sources) != 2 or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in sources.items()
    ):
        raise RepairError('Expected exactly two existing Verilog source files.')
    if not str(diagnostics).startswith('Verilog compile FAILED'):
        raise RepairError('Only actual compilation failures are repairable.')
    if sum(len(s) for s in sources.values()) > 15000:
        raise RepairError('Sources exceed safe repair input limit.')
    target = _target_from_diagnostics(diagnostics, sources)

    # A narrow, objectively justified compiler fix needs no model call at all.
    # It is still only a *proposal*, requiring the existing overwrite approval.
    fixed = _simple_missing_finish_semicolon(target, diagnostics, sources[target])
    if fixed is not None and fixed != sources[target]:
        return target, fixed

    errors = []
    for attempt in range(2):
        try:
            return target, _model_repair(objective, diagnostics, sources, target, model, base_url, attempt)
        except RepairError as exc:
            errors.append(str(exc))
            # Do not repeat network/server failures or an exhausted generation.
            if any(x in str(exc) for x in ('Ollama HTTP', 'request failed', 'ran out of repair tokens')):
                break
    raise RepairError('No valid changed-file proposal after bounded attempts: ' + '; '.join(errors)[:350])
