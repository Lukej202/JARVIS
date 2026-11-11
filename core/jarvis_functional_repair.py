"""Bounded, approval-only functional RTL repair proposals. Does not write or execute."""
import json
import re
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class FunctionalRepairError(ValueError):
    pass


def _module_header(source):
    # Preserve the declared module and port header; do not silently alter interface.
    match = re.search(r'\bmodule\s+([A-Za-z_]\w*)\s*\((.*?)\)\s*;', source, re.S)
    if not match:
        raise FunctionalRepairError('Cannot identify RTL module interface.')
    return match.group(1), re.sub(r'\s+', ' ', match.group(2)).strip()


def propose_verilog_functional_repair(objective, diagnostics, sources, rtl_name, tb_name, model, base_url):
    """Return (rtl_name, proposed_source); task manager handles approval and retry cap."""
    if not isinstance(sources, dict) or set(sources) != {rtl_name, tb_name}:
        raise FunctionalRepairError('Expected exactly the RTL and testbench sources.')
    if not re.search(r'(?im)^Simulation exit code:\s*[1-9]\d*\b', str(diagnostics)):
        raise FunctionalRepairError('No verified failing simulation exit code.')
    if not re.search(r'(?im)(?:^|\n)\s*(?:FATAL:|FAIL\b|ERROR\s*:)', str(diagnostics)):
        raise FunctionalRepairError('No explicit testbench failure in simulation diagnostics.')
    original = sources[rtl_name]
    module, header = _module_header(original)
    if len(original) + len(sources[tb_name]) > 15000:
        raise FunctionalRepairError('Project too large for bounded repair.')
    if not model or not base_url:
        raise FunctionalRepairError('Local repair model not configured.')
    system = ('A self-checking Verilog simulation failed, although the RTL compiled. '
              'Repair ONLY the RTL implementation to satisfy the ORIGINAL user objective and '
              'the existing independent testbench. Never weaken or edit the testbench. '
              'Preserve RTL module name and port declarations exactly, and do not add file I/O, '
              'shell commands or external dependencies. Return one JSON object with keys '
              '"filename" and "content"; filename must exactly equal the specified RTL path, '
              'content must contain the COMPLETE corrected Verilog RTL. No markdown.')
    user = json.dumps({'objective': str(objective)[:700], 'rtl_filename': rtl_name,
                       'testbench_filename': tb_name, 'rtl_source': original,
                       'testbench_source': sources[tb_name],
                       'failed_simulation': str(diagnostics)[:3500]}, ensure_ascii=False)
    errors=[]
    for attempt in range(2):
        payload = {'model': model, 'messages': [
                   {'role':'system','content':system + (' Previous proposal was invalid. Make a concrete RTL change.' if attempt else '')},
                   {'role':'user','content':user}], 'stream':False, 'think':False,
                   'format':'json', 'options': {'num_predict':2800,'temperature':0}}
        req=Request(base_url.rstrip('/')+'/api/chat',data=json.dumps(payload).encode('utf-8'),
                    headers={'Content-Type':'application/json'}, method='POST')
        try:
            with urlopen(req, timeout=180) as response: data=json.load(response)
            if data.get('done_reason')=='length':
                raise FunctionalRepairError('Local model ran out of output tokens.')
            proposal=json.loads((data.get('message') or {}).get('content') or '')
            if not isinstance(proposal,dict) or proposal.get('filename')!=rtl_name:
                raise FunctionalRepairError('Model proposed changing a different file.')
            candidate=proposal.get('content')
            if not isinstance(candidate,str) or not candidate.strip() or candidate==original or len(candidate)>10000:
                raise FunctionalRepairError('Model returned unchanged, empty, or oversized RTL.')
            if _module_header(candidate)!=(module,header):
                raise FunctionalRepairError('Model changed the RTL interface.')
            if len(re.findall(r'\bendmodule\b',candidate))!=1:
                raise FunctionalRepairError('Proposed RTL must contain one complete module.')
            return rtl_name,candidate
        except HTTPError as exc:
            detail=exc.read(500).decode('utf-8','replace')
            errors.append('Ollama HTTP '+str(exc.code)+': '+detail[:200])
        except Exception as exc:
            errors.append(type(exc).__name__+': '+str(exc)[:180])
    raise FunctionalRepairError('No valid RTL proposal: '+'; '.join(errors))
