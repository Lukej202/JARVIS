"""Bounded, local-only plan generation for explicit /task requests.

Only returns data; never executes model-supplied commands.
"""
import json
import os
import re
from urllib.request import Request, urlopen

class PlanningError(ValueError):
    pass


def make_plan(objective: str, model: str, base_url: str) -> dict:
    if not isinstance(objective, str) or not 12 <= len(objective.strip()) <= 700:
        raise PlanningError('Use /task followed by a specific programming objective (12–700 characters).')
    system = (
        'You plan a SMALL local programming project. Reply with a SINGLE valid JSON object, no markdown. '
        'Required schema: {"project":"lowercase_slug","language":"verilog" or "python",'
        '"files":[{"path":"filename or subdir/filename", "content":"complete source code"}],'
        '"run":{"filename":"path relative to project", "testbench":"path relative to project or empty"}}. '
        'Create a NEW project only. Max 4 files. For Verilog, include separate RTL and self-checking testbench; '
        'testbench must call $finish and report PASS or use $fatal on failure; choose run.filename as RTL '
        'and run.testbench as testbench source path. Top module is detected from testbench, do not include it. '
        'For Python, include a runnable Python script and set run.testbench to empty. '
        'Use ordinary text files. Do not write programs that contact networks, access files outside the project, '
        'delete files, run shell commands, install packages, or operate system controls. '
        'Be concise; ensure code is complete and runnable. If objective is not Python/Verilog development '
        'return {"error":"Only Python and Verilog projects are supported in autonomous mode."}.'
    )
    body = {
        'model': model,
        'messages': [{'role':'system','content':system}, {'role':'user','content':objective.strip()}],
        'stream':False, 'think':False, 'format':'json',
        'options':{'num_predict':2800, 'temperature':0},
    }
    req = Request(base_url.rstrip('/')+'/api/chat', data=json.dumps(body).encode('utf-8'),
                  headers={'Content-Type':'application/json'}, method='POST')
    try:
        with urlopen(req, timeout=120) as response:
            result=json.load(response)
    except Exception as exc:
        raise PlanningError(f'Local Ollama planner unavailable: {type(exc).__name__}: {exc}') from exc
    if result.get('done_reason') == 'length':
        raise PlanningError('Planner ran out of tokens; try a smaller programming objective.')
    answer=(result.get('message') or {}).get('content') or ''
    try:
        plan=json.loads(answer)
    except (TypeError, ValueError) as exc:
        raise PlanningError('Planner did not return valid JSON; no files were changed.') from exc
    if not isinstance(plan,dict):
        raise PlanningError('Planner returned an invalid plan.')
    if plan.get('error'):
        raise PlanningError(str(plan['error'])[:300])
    return plan
