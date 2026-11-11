from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from tools.jarvis_workspace_runner import validate_request

class SimulationTopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'verilog').mkdir()
        (self.root/'verilog/design.v').write_text('module counter(input clk); endmodule\n')
    def tb(self, content):
        (self.root/'verilog/design_tb.v').write_text(content)
    def req(self, top='counter'):
        return validate_request(self.root,'verilog/design.v','verilog/design_tb.v',top)
    def test_wrong_top_is_corrected(self):
        self.tb('module counter_tb; counter dut(); endmodule')
        self.assertEqual(self.req()['top_module'], 'counter_tb')
    def test_top_can_be_omitted(self):
        self.tb('module counter_tb; endmodule')
        self.assertEqual(self.req('')['top_module'], 'counter_tb')
    def test_ignores_comments_and_strings(self):
        self.tb('/* module fake; */\nmodule counter_tb; initial $display("module other;"); endmodule')
        self.assertEqual(self.req()['top_module'], 'counter_tb')
    def test_multiple_modules_with_clear_tb(self):
        self.tb('module helper; endmodule\nmodule counter_tb; endmodule')
        self.assertEqual(self.req()['top_module'], 'counter_tb')
    def test_ambiguous_modules_refused(self):
        self.tb('module alpha; endmodule\nmodule beta; endmodule')
        with self.assertRaisesRegex(ValueError,'multiple modules'):
            self.req('counter')
    def test_no_module_refused(self):
        self.tb('// no top module')
        with self.assertRaisesRegex(ValueError,'No module'):
            self.req()
    def test_python_unchanged(self):
        (self.root/'code.py').write_text('print(1)')
        self.assertEqual(validate_request(self.root,'code.py')['language'],'python')
    def test_path_escape_refused(self):
        self.tb('module counter_tb; endmodule')
        with self.assertRaises(ValueError):
            validate_request(self.root,'../elsewhere.v','verilog/design_tb.v','counter_tb')

if __name__ == '__main__':
    unittest.main()
