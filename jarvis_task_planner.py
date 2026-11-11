"""Bounded local task planning for JARVIS supervised workspace tasks.

Task plans are data only. The task manager validates every path and still
requires explicit approval before executing generated programs.
"""
import json
import re
import secrets
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


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



# JARVIS_VERIFIED_SEQUENCE_V1: independent, deterministic bit-pattern reference.
def _sequence_transition(pattern: str, state: int, bit: str) -> int:
    # Length of longest pattern prefix that is a suffix after the next bit.
    prior = pattern[:state] + bit
    return max(k for k in range(len(pattern) + 1) if prior.endswith(pattern[:k]))


def _sequence_plan(objective: str):
    # Generate overlap-aware Moore detector and independent oracle.
    text = objective.lower()
    if not re.search(r'\bsequence\s+detector\b', text):
        return None
    if not re.search(r'\b(?:verilog|systemverilog|rtl|fsm)\b', text):
        return None
    patterns = re.findall(r'(?<![\w])[01]{3,12}(?![\w])', objective)
    if len(set(patterns)) != 1 or not patterns:
        raise PlanningError('Specify exactly one binary detection pattern, 3–12 bits long.')
    pattern = patterns[0]
    # Only support a precise, well-defined behavior for this reference implementation.
    if re.search(r'\b(?:mealy|non[- ]?overlap(?:ping)?|without overlap|no overlap|falling edge|negedge|active.high reset|no reset)\b', text):
        raise PlanningError('This verified sequence template supports a rising-edge Moore detector with overlap and active-low reset only. No files created.')
    n = len(pattern)
    width = max(1, n.bit_length())
    module_name = f'seq_detector_{pattern}'
    tb_name = module_name + '_tb'
    case_lines = []
    for state in range(n + 1):
        zero = _sequence_transition(pattern, state, '0')
        one = _sequence_transition(pattern, state, '1')
        case_lines.append(f"            {width}'d{state}: state <= bit_in ? {width}'d{one} : {width}'d{zero};")
    case_text = '\n'.join(case_lines)
    rtl = f'''// Verified Moore detector for {pattern}; overlapping matches enabled.
// detected is high for one clock interval after the final bit is sampled.
module {module_name} (
    input wire clk,
    input wire rst_n,
    input wire bit_in,
    output wire detected
);
    reg [{width - 1}:0] state;
    assign detected = (state == {width}'d{n});
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            state <= {width}'d0;
        else begin
            case (state)
{case_text}
                default: state <= {width}'d0;
            endcase
        end
    end
endmodule
'''
    # The checker deliberately does NOT derive expected outputs from the RTL
    # state machine. Its independent sliding-window oracle uses the original
    # literal pattern, preventing a self-consistent but wrong DUT/testbench.
    testbench = f'''`timescale 1ns/1ps
module {tb_name};
    localparam integer N = {n};
    localparam [N-1:0] PATTERN = {n}'b{pattern};
    reg clk = 1'b0;
    reg rst_n = 1'b0;
    reg bit_in = 1'b0;
    wire detected;
    reg [N-1:0] history = {{N{{1'b0}}}};
    reg expected = 1'b0;
    integer sampled = 0;
    integer checks = 0;
    integer i;
    reg [31:0] pseudo = 32'h52da9b37;
    {module_name} dut (.clk(clk), .rst_n(rst_n), .bit_in(bit_in), .detected(detected));
    always #5 clk = ~clk;

    task automatic reset_dut;
        begin
            @(negedge clk);
            rst_n = 1'b0;
            bit_in = 1'b0;
            history = {{N{{1'b0}}}};
            sampled = 0;
            expected = 1'b0;
            #1;
            if (detected !== 1'b0)
                $fatal(1, "Reset failed: detected=%b", detected);
            @(negedge clk);
            rst_n = 1'b1;
        end
    endtask

    task automatic feed(input reg next_bit);
        begin
            // Drive away from the rising edge; sample after NBA updates.
            bit_in = next_bit;
            @(posedge clk);
            history = (history << 1) | next_bit;
            sampled = sampled + 1;
            expected = (sampled >= N) && (history == PATTERN);
            #1;
            checks = checks + 1;
            if (detected !== expected)
                $fatal(1, "FAIL: sample=%0d history=%b expected=%b actual=%b", sampled, history, expected, detected);
            @(negedge clk);
        end
    endtask

    initial begin
        $dumpfile("{tb_name}.vcd");
        $dumpvars(0, {tb_name});
        reset_dut();
        // Exercise leading zeroes, then the literal positive pattern.
        for (i = 0; i < N + 2; i = i + 1) feed(1'b0);
'''+''.join(f"        feed(1'b{bit});\n" for bit in pattern)+f'''        // Repeat the pattern without a reset to check overlap handling.
'''+''.join(f"        feed(1'b{bit});\n" for bit in pattern)+f'''        reset_dut();
        // Long deterministic pseudo-random stream: compare every clock.
        for (i = 0; i < 512; i = i + 1) begin
            pseudo = (pseudo >> 1) ^ (pseudo[0] ? 32'h80200003 : 32'h0);
            feed(pseudo[0]);
        end
        $display("PASS: sequence detector {pattern} verified across %0d sampled bits.", checks);
        $finish;
    end
    initial begin
        #100000;
        $fatal(1, "FAIL: testbench timeout");
    end
endmodule
'''
    return {
        'project': f'seq_{pattern}_{secrets.token_hex(3)}',
        'language': 'verilog',
        'files': [{'path': 'design.v', 'content': rtl},
                  {'path': 'design_tb.v', 'content': testbench}],
        'run': {'filename': 'design.v', 'testbench': 'design_tb.v'},
    }


# JARVIS_STAGED_PLANNER_V2: isolated, bounded model requests.
def _chat_json(system: str, user: str, model: str, base_url: str, budget: int) -> dict:
    payload = {
        'model': model,
        'messages': [{'role':'system','content':system}, {'role':'user','content':user}],
        'stream': False, 'think': False, 'format': 'json',
        'options': {'num_predict': budget, 'temperature': 0},
    }
    req = Request(base_url.rstrip('/') + '/api/chat',
                  data=json.dumps(payload).encode('utf-8'),
                  headers={'Content-Type':'application/json'},method='POST')
    try:
        with urlopen(req, timeout=180) as resp:
            result=json.load(resp)
    except HTTPError as exc:
        try:
            detail=exc.read(1500).decode('utf-8','replace')
        except Exception:
            detail=''
        raise PlanningError(f'Ollama HTTP {exc.code}: {detail[:450] or exc.reason}') from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise PlanningError(f'Ollama planning request failed: {type(exc).__name__}: {exc}') from exc
    if result.get('done_reason') == 'length':
        raise PlanningError('Ollama exhausted the generation budget for this stage.')
    content=(result.get('message') or {}).get('content') or ''
    try:
        answer=json.loads(content)
    except (TypeError, ValueError) as exc:
        raise PlanningError('Ollama returned invalid JSON for a planning stage.') from exc
    if not isinstance(answer,dict):
        raise PlanningError('Ollama returned an invalid JSON object.')
    if answer.get('error'):
        raise PlanningError(str(answer['error'])[:250])
    return answer


def _source(answer: dict, *, lang: str, role: str) -> str:
    code=answer.get('code')
    if not isinstance(code,str) or not 20 <= len(code) <= 9500:
        raise PlanningError(f'{role} generation did not return complete source code.')
    if '```' in code:
        raise PlanningError(f'{role} generation included markdown rather than source.')
    if lang == 'verilog':
        if not re.search(r'\bmodule\s+[a-zA-Z_]\w*',code) or not re.search(r'\bendmodule\b',code):
            raise PlanningError(f'{role} is missing a Verilog module.')
        if role == 'testbench' and re.search(r'\?\s*\$\s*(?:display|fatal)\s*\(', code):
            raise PlanningError('Generated testbench uses system tasks as ternary expressions; refusing invalid source.')
        if role=='testbench' and not ('$finish' in code and ('PASS' in code or '$fatal' in code)):
            raise PlanningError('Testbench must finish and explicitly verify expected behavior.')
    return code


def _slug(objective: str) -> str:
    words=re.findall(r'[a-z0-9]+',objective.lower())
    if 'sequence' in words and 'detector' in words:
        match=re.search(r'\b[01]{3,12}\b', objective)
        return 'sequence_detector_'+(match.group() if match else 'rtl')
    useful=[w for w in words if w not in {'create','write','make','a','an','the','and','in','for','verilog','python','testbench','test','simulate','verify','it','self','checking','results'}]
    return ('_'.join(useful[:3]) or 'project')[:26].strip('_')


def make_plan(objective: str, model: str, base_url: str) -> dict:
    if not isinstance(objective,str) or not 12 <= len(objective.strip()) <= 700:
        raise PlanningError('Use /task followed by a specific programming objective (12–700 characters).')
    # Specification-derived deterministic templates take precedence over Qwen.
    sequence_template = _sequence_plan(objective)
    if sequence_template is not None:
        return sequence_template
    # Preserve known-good deterministic counter template.
    template=_counter_plan(objective)
    if template is not None:
        return template
    objective=objective.strip()
    if re.search(r'\b(?:verilog|systemverilog|rtl|sequence detector|fsm)\b',objective,re.I):
        language='verilog'
    elif re.search(r'\bpython\b',objective,re.I):
        language='python'
    else:
        raise PlanningError('Specify a Python or Verilog project for autonomous programming.')

    # Metadata is determined by JARVIS; no code or project paths are accepted from model.
    prefix=_slug(objective)
    project=(prefix[:25]+'_'+secrets.token_hex(3))[:33]
    if language=='verilog':
        rtl_name='design.v'; tb_name='design_tb.v'
        rtl_answer=_chat_json(
            'You implement ONE synthesizable Verilog module. Return exactly JSON '
            '{"code":"complete Verilog RTL source"}. No explanation, markdown, extra files, '
            'testbench, shell commands, file access, or network functions. '
            'Use Verilog compatible with Icarus -g2012. Keep the module interface simple.',
            'User objective: '+objective+'\nGenerate the RTL design ONLY, including complete module and endmodule. '
            'Do not replace the user objective with any earlier project.',
            model,base_url,1400)
        rtl=_source(rtl_answer,lang='verilog',role='RTL')
        # Objective lock for the previously observed failure mode.
        seq=re.search(r'\b[01]{3,12}\b',objective)
        if re.search(r'\bsequence\s+detector\b',objective,re.I):
            if not re.search(r'\b(?:detect|match|sequence)\w*\b',rtl,re.I):
                raise PlanningError('RTL does not appear to implement a sequence detector; no files created.')
            if seq and seq.group() not in rtl:
                raise PlanningError('RTL does not contain the requested sequence '+seq.group()+'; no files created.')
        tb_answer=_chat_json(
            'You write exactly ONE Verilog self-checking testbench for the supplied RTL. '
            'Reply only JSON {"code":"complete Verilog testbench source"}. '
            'No markdown. Instantiate the actual module using its EXACT ports. '
            'Generate clock and reset as required. Test positive and negative cases. '
            'Use $fatal(1,...) on mismatch, print PASS only after ALL checks succeed, '
            'call $finish, and include a finite timeout. Do not use external files '
            'except $dumpfile/$dumpvars for waveform. Compatible with iverilog -g2012.',
            'Original required behavior: '+objective+'\nThis is the EXACT RTL to test; use its module and ports:\n'+rtl,
            model,base_url,2200)
        tb=_source(tb_answer,lang='verilog',role='testbench')
        return {'project':project,'language':'verilog',
                'files':[{'path':rtl_name,'content':rtl},{'path':tb_name,'content':tb}],
                'run':{'filename':rtl_name,'testbench':tb_name}}

    py_answer=_chat_json(
        'Write one safe standalone Python 3 script. Return only JSON '
        '{"code":"complete runnable Python source"}. No markdown or shell. '
        'Do not access the network, user files, external directories, environment variables, '
        'install packages, run subprocesses, or change system settings. '
        'Include deterministic self-tests and print PASS only when assertions pass.',
        'Original objective: '+objective+'\nProduce one complete Python script for this objective.',
        model,base_url,2200)
    code=_source(py_answer,lang='python',role='Python')
    return {'project':project,'language':'python',
            'files':[{'path':'main.py','content':code}],
            'run':{'filename':'main.py','testbench':''}}
