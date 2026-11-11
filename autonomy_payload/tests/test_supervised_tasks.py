import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.jarvis_task_manager import TaskManager, validated_plan, TaskError

PLAN={
    'project':'counter_demo', 'language':'verilog',
    'files': [
        {'path':'rtl/counter.v','content':'module counter(input clk); endmodule\n'},
        {'path':'tb/counter_tb.v','content':'module counter_tb; counter dut(); initial begin $display("PASS"); $finish; end endmodule\n'},
    ],
    'run':{'filename':'rtl/counter.v','testbench':'tb/counter_tb.v'}
}

class TestTasks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)/'workspace'
        self.root.mkdir()
        self.actions={}
        self.index=0
        def lookup(task,idx):
            for aid,entry in self.actions.items():
                if entry['payload']['_task_id']==task and entry['payload']['_task_step']==idx:
                    return aid,entry['status'],entry['result']
            return None
        def queue(kind,payload,summary):
            self.index+=1
            aid=f'{self.index:012x}'
            self.actions[aid]={'kind':kind,'payload':payload,'status':'pending','result':''}
            return aid
        self.m=TaskManager(self.root,store_path=Path(self.tmp.name)/'tasks.db',
                           approval_lookup=lookup,queue_approval=queue)
    def tearDown(self):self.tmp.cleanup()

    def test_plan_and_resume_approval(self):
        with patch('core.jarvis_task_manager.make_plan',return_value=PLAN):
            msg=self.m.start('Create a verilog counter with a testbench', 'mock', 'http://localhost')
        self.assertIn('waiting for approval',msg)
        task=self.m.store.active()
        self.assertTrue((self.root/'projects/counter_demo/rtl/counter.v').is_file())
        self.assertTrue((self.root/'projects/counter_demo/tb/counter_tb.v').is_file())
        self.assertEqual(task['status'],'waiting_approval')
        self.assertEqual(len(self.actions),1)
        self.assertEqual(self.m.resume().split('waiting')[0],f"Task `{task['id']}` ")
        self.assertEqual(len(self.actions),1)
        aid=task['approval_id']
        self.assertTrue(self.m.may_execute(task['id'],task['step_index'],aid))
        self.actions[aid]['status']='completed'
        self.actions[aid]['result']='Verilog compiled successfully\nSimulation exit code: 0\nSimulation output:\nPASS'
        msg=self.m.after_decision(aid,True,True,self.actions[aid]['result'])
        self.assertIn('completed',msg)
        self.assertIsNone(self.m.store.active())
        self.assertEqual(len(self.actions),1)
    def test_cancel_disallows_execution(self):
        with patch('core.jarvis_task_manager.make_plan',return_value=PLAN):
            self.m.start('Create a verilog counter with a testbench','mock','http://localhost')
        task=self.m.store.active();aid=task['approval_id'];idx=task['step_index']
        self.m.cancel()
        self.assertFalse(self.m.may_execute(task['id'],idx,aid))
    def test_failure_stops(self):
        with patch('core.jarvis_task_manager.make_plan',return_value=PLAN):
            self.m.start('Create a verilog counter with a testbench','mock','http://localhost')
        task=self.m.store.active();aid=task['approval_id']
        msg=self.m.after_decision(aid,True,True,'Verilog compile FAILED (exit 1): bad module')
        self.assertIn('stopped',msg)
        self.assertIsNone(self.m.store.active())
    def test_reject_escape(self):
        bad=dict(PLAN)
        bad['files']=[{'path':'../oops.v','content':'module x;endmodule'}]
        with self.assertRaises(TaskError):validated_plan(self.root,bad)
    def test_reject_existing_project(self):
        (self.root/'projects/counter_demo').mkdir(parents=True)
        with self.assertRaises(TaskError):validated_plan(self.root,PLAN)
    def test_reject_missing_tb(self):
        bad={**PLAN,'run':{'filename':'rtl/counter.v','testbench':''}}
        with self.assertRaises(TaskError):validated_plan(self.root,bad)
    def test_no_overwrite_on_plan(self):
        with patch('core.jarvis_task_manager.make_plan',return_value=PLAN):
            self.m.start('Create a verilog counter with a testbench','mock','http://localhost')
            msg=self.m.start('Create another verilog counter with a testbench','mock','http://localhost')
        self.assertIn('already',msg.replace('is active','already active'))

if __name__=='__main__': unittest.main()
