import io
import json
import unittest
from unittest.mock import patch
from core.jarvis_task_repair import propose_verilog_repair, RepairError

TARGET = 'projects/repair_demo_12e096eb/counter_4bit_tb.v'
RTL = 'projects/repair_demo_12e096eb/counter_4bit.v'
BROKEN = '''module counter_4bit_tb;
initial begin
 $display("hello");
 $finish
end
endmodule
'''
DIAG = 'Verilog compile FAILED (exit 2):\n/home/u/JARVIS/workspace/' + TARGET + ':5: syntax error\n' + TARGET + ':6: error: Malformed statement'

class Reply:
    def __init__(self, data): self.f = io.BytesIO(json.dumps(data).encode())
    def __enter__(self): return self.f
    def __exit__(self, *a): self.f.close()

def resp(filename, content):
    return Reply({'message': {'content':json.dumps({'filename':filename,'content':content})}})

class Tests(unittest.TestCase):
    def test_fixture_is_fixed_without_model(self):
        with patch('core.jarvis_task_repair.urlopen', side_effect=AssertionError('unexpected model call')):
            name, content = propose_verilog_repair('counter', DIAG, {RTL:'module dut;endmodule',TARGET:BROKEN},'m','http://localhost')
        self.assertEqual(name, TARGET)
        self.assertIn('$finish;', content)
        self.assertNotEqual(content, BROKEN)
    def test_wrong_file_then_valid_reply(self):
        src = 'module tb; initial begin $display("a"); end endmodule\n'
        diag = 'Verilog compile FAILED (exit 2):\n' + TARGET + ':1: syntax error'
        with patch('core.jarvis_task_repair.urlopen', side_effect=[resp(RTL,src),resp(TARGET,src+'// fixed\n')]) as mock:
            name, content = propose_verilog_repair('counter',diag,{RTL:'module dut;endmodule',TARGET:src},'m','http://localhost')
        self.assertEqual(name,TARGET)
        self.assertEqual(mock.call_count, 2)
        self.assertIn('fixed',content)
    def test_unchanged_twice_stops(self):
        src = 'module tb; initial begin $display("a"); end endmodule\n'
        diag = 'Verilog compile FAILED (exit 2):\n' + TARGET + ':1: syntax error'
        with patch('core.jarvis_task_repair.urlopen', side_effect=[resp(TARGET,src),resp(TARGET,src)]) as mock:
            with self.assertRaisesRegex(RepairError,'unchanged'):
                propose_verilog_repair('counter',diag,{RTL:'module dut;endmodule',TARGET:src},'m','http://localhost')
        self.assertEqual(mock.call_count,2)
    def test_no_fallback_without_matching_error(self):
        with self.assertRaises(RepairError):
            propose_verilog_repair('counter','Verilog compile FAILED (exit 2):\nother.v:5: syntax error', {RTL:'module dut;endmodule',TARGET:BROKEN},'m','http://localhost')
    def test_cannot_modify_multiple_missing_semicolons_via_fallback(self):
        src = 'module tb;\ninitial begin\n$finish\nend\ninitial begin\n$finish\nend\nendmodule\n'
        diag = 'Verilog compile FAILED (exit 2):\n' + TARGET + ':4: syntax error\n' + TARGET + ':7: syntax error'
        with patch('core.jarvis_task_repair.urlopen', side_effect=[resp(TARGET,src),resp(TARGET,src)]) as mock:
            with self.assertRaises(RepairError):
                propose_verilog_repair('counter',diag,{RTL:'module dut;endmodule',TARGET:src},'m','http://localhost')
        self.assertEqual(mock.call_count,2)

if __name__ == '__main__': unittest.main()
