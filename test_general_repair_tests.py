import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from core.jarvis_task_manager import TaskManager
from core.jarvis_task_repair import _simple_missing_finish_semicolon

class GeneralRepairTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.workspace=Path(tmp.name)/'workspace'; self.workspace.mkdir()
        self.actions=[]
        def queue(kind,payload,description):
            action={'id':str(len(self.actions)+1),'kind':kind,'payload':payload,'status':'pending'}
            self.actions.append(action)
            return action['id']
        def lookup(tid,idx):
            for a in reversed(self.actions):
                if a['kind']=='run_workspace_program' and a['payload'].get('_task_id')==tid and a['payload'].get('_task_step')==idx:
                    return a['id'],a['status'],a.get('result','')
        self.mgr=TaskManager(self.workspace, store_path=self.workspace.parent/'tasks.db',
            approval_lookup=lookup,queue_approval=queue,model='qwen3.5:4b',ollama_url='http://localhost:11434')

    def check_variant(self,variant):
        response=self.mgr.start_repair_test(variant)
        self.assertIn('NEW disposable project',response)
        task=self.mgr.store.active()
        self.assertEqual(task['plan']['_repair_test_kind'],variant)
        self.assertEqual(task['status'],'waiting_approval')
        self.assertEqual(self.actions[-1]['kind'],'run_workspace_program')
        self.assertEqual(len(list((self.workspace/'projects').iterdir())),1)
        return task

    def test_bad_named_port(self):
        task=self.check_variant('port')
        tb=(self.workspace/task['steps'][-1]['testbench']).read_text()
        self.assertIn('.clock_invalid(clk)',tb)
        self.assertIn('        $finish;',tb)
        self.assertNotIn('        $finish\n',tb)
        self.assertIsNone(_simple_missing_finish_semicolon(task['steps'][-1]['testbench'],
            'Verilog compile FAILED: error: unknown port clock_invalid',tb))

    def test_undeclared_signal(self):
        task=self.check_variant('signal')
        rtl=(self.workspace/task['steps'][-1]['filename']).read_text()
        self.assertIn('`default_nettype none',rtl)
        self.assertIn('missing_signal',rtl)
        self.assertIn('        $finish;', (self.workspace/task['steps'][-1]['testbench']).read_text())

    def test_separate_attempt_requires_model_proposal(self):
        task=self.check_variant('port')
        run=self.actions[-1]
        target=task['steps'][-1]['testbench']
        old=(self.workspace/target).read_text()
        corrected=old.replace('.clock_invalid(clk)', '.clk(clk)',1)
        with patch('core.jarvis_task_repair.propose_verilog_repair',return_value=(target,corrected)) as proposer:
            result=self.mgr.after_decision(run['id'],True,True,
                'Verilog compile FAILED (exit 1):\n'+target+':6: error: port clock_invalid is not a port of dut.')
        proposer.assert_called_once()
        self.assertIn('overwrite approval',result)
        self.assertEqual(self.actions[-1]['kind'],'write_file')
        self.assertEqual((self.workspace/target).read_text(),old)

    def test_active_task_blocks_new_test(self):
        self.check_variant('port')
        self.assertIn('Another autonomous task',self.mgr.start_repair_test('signal'))
        self.assertEqual(len(self.actions),1)

if __name__=='__main__': unittest.main()
