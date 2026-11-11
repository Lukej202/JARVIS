"""Unit tests that do not need Ollama, Flask, Icarus, or workspace changes."""
import unittest, importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location('repair_planner',Path(__file__).parent/'jarvis_task_planner.py')
planner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)

class SequenceRepairTests(unittest.TestCase):
    def test_1011_plan_is_correctly_named(self):
        p=planner.make_plan('Create a Verilog sequence detector for 1011, write a self-checking testbench, simulate it, and verify the results.','unused','unused')
        self.assertEqual(p['language'],'verilog')
        self.assertEqual(p['run'], {'filename':'design.v','testbench':'design_tb.v'})
        self.assertEqual(len(p['files']),2)
        rtl=p['files'][0]['content'];tb=p['files'][1]['content']
        self.assertIn('seq_detector_1011',rtl)
        self.assertIn('PATTERN = 4\'b1011',tb)
        self.assertIn('if (detected !== expected)',tb)
        self.assertIn('$fatal(1',tb)
        self.assertIn('PASS: sequence detector 1011',tb)
        self.assertNotIn('Matched \'111\'',rtl)

    def test_transition_oracle_all_3_to_8_bit_patterns(self):
        # Validate *all states and both transitions* against an independent
        # suffix-of-stream reference for every 3-8 bit pattern.
        for length in range(3,9):
            for value in range(1<<length):
                pat=format(value,f'0{length}b')
                for state in range(length+1):
                    for bit in '01':
                        next_state=planner._sequence_transition(pat,state,bit)
                        stream=pat[:state]+bit
                        reference=max(k for k in range(length+1) if stream.endswith(pat[:k]))
                        self.assertEqual(next_state, reference)

    def test_repeated_overlap(self):
        pat='1011'; stream='1011011'; state=0; detections=[]
        for i,bit in enumerate(stream):
            state=planner._sequence_transition(pat,state,bit)
            if state==len(pat):detections.append(i)
        self.assertEqual(detections,[3,6])

    def test_declines_ambiguous_variant(self):
        with self.assertRaises(planner.PlanningError):
            planner.make_plan('Make a nonoverlapping Verilog sequence detector 1011 and a testbench','unused','unused')

    def test_preserves_basic_counter(self):
        p=planner.make_plan('Create an 8-bit counter in Verilog and verify with a testbench','unused','unused')
        self.assertTrue(p['project'].startswith('counter_8bit'))

    def test_rejects_illegal_tb_ternary(self):
        with self.assertRaises(planner.PlanningError):
            planner._source({'code':"module tb; initial begin foo ? $display(\"ok\") : $fatal(1,\"no\"); $finish; end endmodule"},lang='verilog',role='testbench')

    def test_model_not_called_for_pattern(self):
        original=planner._chat_json
        try:
            planner._chat_json=lambda *args,**kwargs: self.fail('Model was unexpectedly called')
            planner.make_plan('Create a Verilog sequence detector for 0011 and simulate with testbench','model','http://none')
        finally:
            planner._chat_json=original

if __name__=='__main__':unittest.main()
