import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from core.jarvis_task_manager import TaskManager

class ReportingTests(unittest.TestCase):
    def setup_task(self, folder):
        root = Path(folder)/'workspace'; root.mkdir()
        manager = TaskManager(root,store_path=Path(folder)/'tasks.db',approval_lookup=lambda *a:None,queue_approval=lambda *a:'id')
        manager.store.create('example','Test',{'language':'verilog'},[{'kind':'run','filename':'projects/a/a.v','testbench':'projects/a/a_tb.v'}])
        return manager
    def test_pass(self):
        with TemporaryDirectory() as d:
            m=self.setup_task(d)
            r=m._apply_run_result('example',0,'Simulation exit code: 0\nPASS: counter works\nWaveform(s): simulations/test.vcd')
            self.assertIn('Verification: PASS',r)
            self.assertEqual(m.store.get('example')['status'],'completed')
    def test_success_no_assertion(self):
        with TemporaryDirectory() as d:
            m=self.setup_task(d)
            r=m._apply_run_result('example',0,'Simulation exit code: 0\nSimulation output: (no output)')
            self.assertIn('verification unconfirmed',r)
    def test_failure_with_zero_exit(self):
        with TemporaryDirectory() as d:
            m=self.setup_task(d)
            r=m._apply_run_result('example',0,'Simulation exit code: 0\nFAIL: wrong counter')
            self.assertIn('failed verification',r)
            self.assertEqual(m.store.get('example')['status'],'failed')
    def test_nonzero_exit(self):
        with TemporaryDirectory() as d:
            m=self.setup_task(d)
            r=m._apply_run_result('example',0,'Simulation exit code: 1')
            self.assertIn('failed during execution',r)
