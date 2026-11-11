import importlib.util, json, unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('planner',Path(__file__).with_name('jarvis_task_planner_v2.py'))
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
OBJ='Create a Verilog sequence detector for 1011, write a self-checking testbench, simulate it and verify results.'
RTL='module detector(input clk, input rst, input serial_in, output reg detected); reg [3:0] shift; always @(posedge clk) begin if (rst) begin shift<=0; detected<=0; end else begin shift<={shift[2:0],serial_in}; detected<=({shift[2:0],serial_in}==4\'b1011); end end endmodule'
TB='module detector_tb; reg clk=0,rst=1,serial_in=0; wire detected; detector dut(.clk(clk),.rst(rst),.serial_in(serial_in),.detected(detected)); always #5 clk=~clk; initial begin #12 rst=0; repeat(2) @(negedge clk); $display("PASS"); $finish; end initial begin #1000 $fatal(1,"timeout"); end endmodule'
class TestPlanner(unittest.TestCase):
 def test_staged_two_calls(self):
  calls=[]
  def mock(system,user,model,url,budget):
   calls.append((system,user,budget));return {'code': RTL if len(calls)==1 else TB}
  with patch.object(p,'_chat_json',side_effect=mock):
   plan=p.make_plan(OBJ,'qwen3.5:4b','http://localhost:11434')
  self.assertEqual(len(calls),2)
  self.assertEqual(plan['run']['testbench'],'design_tb.v')
  self.assertIn(RTL,calls[1][1]);self.assertIn('1011',calls[0][1])
 def test_objective_lock(self):
  wrong='module counter(input clk,output reg [7:0] count); always @(posedge clk) count<=count+1; endmodule'
  with patch.object(p,'_chat_json',return_value={'code':wrong}):
   with self.assertRaisesRegex(p.PlanningError,'sequence detector'):
    p.make_plan(OBJ,'model','http://localhost')
 def test_ollama_error_body(self):
  from urllib.error import HTTPError
  from io import BytesIO
  e=HTTPError('url',500,'internal',{},BytesIO(b'{"error":"runner crashed"}'))
  with patch.object(p,'urlopen',side_effect=e):
   with self.assertRaisesRegex(p.PlanningError,'runner crashed'):
    p._chat_json('a','b','c','http://localhost',100)
 def test_counter_template_unchanged(self):
  plan=p.make_plan('Create an 8-bit Verilog counter and testbench and simulate it','model','url')
  self.assertEqual(plan['language'],'verilog')
  self.assertIn('counter',plan['project'])
if __name__=='__main__':unittest.main()
