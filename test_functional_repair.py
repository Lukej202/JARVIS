import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from core.jarvis_task_manager import TaskManager
from core.jarvis_functional_repair import FunctionalRepairError, propose_verilog_functional_repair

class FunctionalRepairTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.root=Path(t.name)/'workspace'; self.root.mkdir()
        self.actions=[]
        def queue(kind,payload,summary):
            record={'id':str(len(self.actions)+1),'kind':kind,'payload':payload,'status':'pending'}
            self.actions.append(record);return record['id']
        def lookup(tid,idx):
            for a in reversed(self.actions):
                if a['kind']=='run_workspace_program' and a['payload'].get('_task_id')==tid and a['payload'].get('_task_step')==idx:
                    return a['id'],a['status'],a.get('result','')
        self.mgr=TaskManager(self.root,store_path=self.root.parent/'tasks.db',approval_lookup=lookup,
                             queue_approval=queue,model='test-model',ollama_url='http://localhost:11434')

    def fixture(self):
        msg=self.mgr.start_repair_test('functional')
        self.assertIn('NEW disposable project',msg)
        task=self.mgr.store.active();self.assertIsNotNone(task)
        rtl=task['steps'][-1]['filename'];tb=task['steps'][-1]['testbench']
        self.assertIn("count <= count - 4'd1;",(self.root/rtl).read_text())
        return task,rtl,tb

    def test_fixture_preserves_checking_testbench(self):
        task,rtl,tb=self.fixture()
        self.assertIn('if (count !== expected)',(self.root/tb).read_text())
        self.assertIn('$fatal(', (self.root/tb).read_text())

    def test_failed_simulation_proposes_only_rtl_without_overwrite(self):
        task,rtl,tb=self.fixture()
        original=(self.root/rtl).read_text()
        corrected=original.replace("count <= count - 4'd1;", "count <= count + 4'd1;", 1)
        with patch('core.jarvis_functional_repair.propose_verilog_functional_repair',return_value=(rtl,corrected)) as fn:
            msg=self.mgr.after_decision(self.actions[-1]['id'],True,True,
                'Verilog compiled successfully: x\nSimulation exit code: 1\nSimulation output:\nFATAL: tb.v:20: Mismatch got 15 expected 1')
        fn.assert_called_once()
        self.assertIn('overwrite approval',msg)
        self.assertEqual(self.actions[-1]['kind'],'write_file')
        self.assertEqual(self.actions[-1]['payload']['filename'],rtl)
        self.assertEqual((self.root/rtl).read_text(),original)
        self.assertEqual(self.mgr.store.active()['plan']['_repair_attempts'],1)

    def test_approved_write_then_separate_run_approval(self):
        task,rtl,tb=self.fixture()
        old=(self.root/rtl).read_text();corrected=old.replace("count <= count - 4'd1;", "count <= count + 4'd1;",1)
        with patch('core.jarvis_functional_repair.propose_verilog_functional_repair',return_value=(rtl,corrected)):
            self.mgr.after_decision(self.actions[-1]['id'],True,True,
                'Simulation exit code: 1\nFATAL: failed check')
        approval=self.actions[-1]
        (self.root/rtl).write_text(corrected)
        self.mgr.after_decision(approval['id'],True,True,'Saved '+rtl)
        self.assertEqual(self.actions[-1]['kind'],'run_workspace_program')
        self.assertNotEqual(self.actions[-1]['id'],approval['id'])
        self.assertEqual(self.mgr.store.active()['status'],'waiting_approval')
        passed='Simulation exit code: 0\nSimulation output:\nPASS: 4-bit counter incremented and rolled over correctly.'
        msg=self.mgr.after_decision(self.actions[-1]['id'],True,True,passed)
        self.assertIn('Verification: PASS',msg)
        self.assertIsNone(self.mgr.store.active())

    def test_no_repair_on_unrelated_execution_failure(self):
        self.fixture()
        with patch('core.jarvis_functional_repair.propose_verilog_functional_repair') as fn:
            self.mgr.after_decision(self.actions[-1]['id'],True,True,
                'Simulation exit code: 1\nExecution killed due to resource limits')
        fn.assert_not_called()
        self.assertIsNone(self.mgr.store.active())

    def test_denial_stops_without_overwrite(self):
        task,rtl,tb=self.fixture()
        original=(self.root/rtl).read_text()
        with patch('core.jarvis_functional_repair.propose_verilog_functional_repair',return_value=(rtl,original+'\n// fix')):
            self.mgr.after_decision(self.actions[-1]['id'],True,True,
                                    'Simulation exit code: 1\nFATAL: mismatch')
        self.mgr.after_decision(self.actions[-1]['id'],False,False,'denied')
        self.assertEqual((self.root/rtl).read_text(),original)
        self.assertIsNone(self.mgr.store.active())

    def test_repair_proposal_rejects_testbench_change(self):
        rtl='projects/x/design.v';tb='projects/x/design_tb.v'
        original='module design(input wire clk, output reg value);\nendmodule\n'
        sources={rtl:original,tb:'module tb; endmodule'}
        bad={'message':{'content':json.dumps({'filename':tb,'content':'module tb; endmodule // edited'})}}
        class Resp:
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with patch('core.jarvis_functional_repair.urlopen',return_value=Resp()),patch('core.jarvis_functional_repair.json.load',return_value=bad):
            with self.assertRaises(FunctionalRepairError):
                propose_verilog_functional_repair('fix counter','Simulation exit code: 1\nFATAL: mismatch',sources,rtl,tb,'model','http://localhost')

if __name__=='__main__': unittest.main()
