"""Bounded local task planning for JARVIS supervised workspace tasks.

Task plans are data only. The task manager validates every path and still
requires explicit approval before executing generated programs.
"""
import json
import re
import secrets
from urllib.request import Request, urlopen


class PlanningError(ValueError):
    pass


def _counter_plan(objective: str):
    """Reliable starter template for requested Verilog counter/testbench projects.

    Avoid spending a model generation budget on a straightforward RTL example.
    This does not execute anything or bypass the task manager's approvals.
    """
    text = objective.lower()
    if not re.search(r'\bcounter\b', text) or not re.search(r'\b(?:testbench|test bench|simulate|simulation|verify|test)\b', text):
        return None
    if re.search(r'\bpython\b', text) or not re.search(r'\b(?:verilog|rtl|systemverilog)\b', text):
        return None
    widths = re.findall(r'\b(\d{1,2})\s*[- ]?bit\b', text)
    if len(set(widths)) != 1:
        return None
    width = int(widths[0])
    if width not in (4, 8, 16):
        return None
    # Only use the template for a basic up counter. Other variations stay with
    # the general planner rather than silently substituting a different design.
    if re.search(r'\b(?:down|up.down|bidirectional|gray|johnson|ring|decade|bcd|modulo|saturat|enable|loadable|preset|asynchronous counter)\b', text):
        return None

    dut = f'counter_{width}bit'
    tb = dut + '_tb'
    maximum = (1 << width) - 1
    rtl = f'''module {dut} (
    input wire clk,
    input wire rst_n,
    output reg [{width - 1}:0] count
);
    always @(posedge clk) begin
        if (!rst_n)
            count <= {width}'d0;
        else
            count <= count + {width}'d1;
    end
endmodule
'''
    # Self-check every rising-edge count and rollover, with a bounded
    # simulation and explicit nonzero failure. This is intentionally basic.
    testbench = f'''`timescale 1ns/1ps
module {tb};
    reg clk = 1'b0;
    reg rst_n = 1'b0;
    wire [{width - 1}:0] count;
    reg [{width - 1}:0] expected = {width}'d0;
    integer i;
    {dut} dut (.clk(clk), .rst_n(rst_n), .count(count));
    always #5 clk = ~clk;
    initial begin
        $dumpfile("{tb}.vcd");
        $dumpvars(0, {tb});
        // Check reset and all values through rollover.
        @(negedge clk);
        if (count !== {width}'d0) $fatal(1, "Reset failed: %d", count);
        rst_n = 1'b1;
        for (i = 0; i < {maximum + 1}; i = i + 1) begin
            @(posedge clk);
            expected = expected + {width}'d1;
            #1; // allow nonblocking assignments to update
            if (count !== expected)
                $fatal(1, "Mismatch at %0d: got %0d expected %0d", i, count, expected);
        end
        $display("PASS: {width}-bit counter incremented and rolled over correctly.");
        $finish;
    end
    initial begin
        #{(maximum + 2) * 12 + 100} $fatal(1, "Testbench timeout");
    end
endmodule
'''
    return {
        'project': f'counter_{width}bit_{secrets.token_hex(3)}',
        'language': 'verilog',
        'files': [
            {'path': f'{dut}.v', 'content': rtl},
            {'path': f'{tb}.v', 'content': testbench},
        ],
        'run': {'filename': f'{dut}.v', 'testbench': f'{tb}.v'},
    }


def _ask_model(objective: str, model: str, base_url: str, num_predict: int) -> dict:
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
    payload = {
        'model': model,
        'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': objective.strip()}],
        'stream': False,
        'think': False,
        'format': 'json',
        'options': {'num_predict': num_predict, 'temperature': 0},
    }
    req = Request(
        base_url.rstrip('/') + '/api/chat',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'}, method='POST',
    )
    try:
        with urlopen(req, timeout=180) as response:
            result = json.load(response)
    except Exception as exc:
        raise PlanningError(f'Local Ollama planner unavailable: {type(exc).__name__}: {exc}') from exc
    if result.get('done_reason') == 'length':
        raise PlanningError('The local model exhausted its planning token budget.')
    answer = (result.get('message') or {}).get('content') or ''
    try:
        plan = json.loads(answer)
    except (TypeError, ValueError) as exc:
        raise PlanningError('The local planner returned invalid JSON.') from exc
    if not isinstance(plan, dict):
        raise PlanningError('The local planner returned an invalid plan.')
    if plan.get('error'):
        raise PlanningError(str(plan['error'])[:300])
    return plan


def make_plan(objective: str, model: str, base_url: str) -> dict:
    if not isinstance(objective, str) or not 12 <= len(objective.strip()) <= 700:
        raise PlanningError('Use /task followed by a specific programming objective (12–700 characters).')
    plan = _counter_plan(objective)
    if plan is not None:
        return plan
    # Retry only plan *generation*, which has no side effects. Never retry
    # executing a program or an approved action.
    try:
        return _ask_model(objective, model, base_url, num_predict=4096)
    except PlanningError as exc:
        if 'exhausted its planning token budget' not in str(exc):
            raise
    try:
        return _ask_model(objective, model, base_url, num_predict=8192)
    except PlanningError as exc:
        raise PlanningError(f'{exc} No code or actions were executed; try splitting a complex project.') from exc
