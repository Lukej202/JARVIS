import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from core.jarvis_task_repair import RepairError, propose_verilog_repair
from core.jarvis_task_manager import TaskManager

class RepairTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'workspace'
        self.root.mkdir()
        self.approvals=[]
        self.calls={}
        def lookup(task_id, index):
            for item in reversed(self.approvals):
                if item['kind']=='run_workspace_program' and item['payload'].get('_task_id')==task_id and item['payload'].get('_task_step')==index:
                    return item['id'],item['status'],item.get('result')
            return None
        def queue(kind,payload,summary):
            number=len(self.approvals)+1
            item={'id':f'{number:012x}','kind':kind,'payload':payload,'status':'pending'}
            self.approvals.append(item)
            return item['id']
        self.manager=TaskManager(self.root, store_path=self.root.parent/'tasks.sqlite',approval_lookup=lookup,
                                 queue_approval=queue,model='test-model',ollama_url='http://localhost:11434')
        self.project=self.root/'projects'/'repair_test'
        self.project.mkdir(parents=True)
        self.rtl='module dut(input a, output b); assign b=a; endmodule\n'
        self.tb='module dut_tb; initial $finish; endmodule\n'
        (self.project/'design.v').write_text(self.rtl)
        (self.project/'design_tb.v').write_text(self.tb)
        self.task='abcdabcdabcd'
        plan={'project':'repair_test','language':'verilog','files':[], 'run':{'filename':'design.v','testbench':'design_tb.v'}}
        steps=[{'kind':'run','filename':'projects/repair_test/design.v','testbench':'projects/repair_test/design_tb.v'}]
        self.manager.store.create(self.task,'Make a test module in Verilog',plan,steps)
        self.run_id=self.manager._advance(self.task)
    def test_bounded_repair_and_approved_rerun(self):
        self.assertEqual(len(self.approvals),1)
        first=self.approvals[0]
        first['status']='completed'
        diagnostics='Verilog compile FAILED (exit 2):\nprojects/repair_test/design_tb.v:2: syntax error'
        first['result']=diagnostics
        revised='module dut_tb; initial begin $display("PASS: good"); $finish; end endmodule\n'
        with patch('core.jarvis_task_repair.propose_verilog_repair',return_value=('projects/repair_test/design_tb.v',revised)) as llm:
            msg=self.manager.after_decision(first['id'],True,True,diagnostics)
        self.assertIn('awaits overwrite approval',msg)
        self.assertEqual((self.project/'design_tb.v').read_text(),self.tb)
        self.assertEqual(self.approvals[-1]['kind'],'write_file')
        self.assertTrue(self.manager.may_execute(self.task,0,self.approvals[-1]['id']))
        write=self.approvals[-1]
        self.assertEqual(write['payload']['_expected_sha256'],hashlib.sha256(self.tb.encode()).hexdigest())
        # Existing approved action handler writes the proposed file. No automatic write.
        (self.project/'design_tb.v').write_text(revised)
        write['status']='completed'
        msg=self.manager.after_decision(write['id'],True,True,'Saved new testbench')
        self.assertIn('waiting for approval',msg)
        self.assertEqual(len(self.approvals),3)
        self.assertEqual(self.approvals[-1]['kind'],'run_workspace_program')
        self.assertTrue(self.manager.may_execute(self.task,0,self.approvals[-1]['id']))
        newrun=self.approvals[-1]
        newrun['status']='completed'
        result='Verilog compiled successfully:\nSimulation exit code: 0\nSimulation output:\nPASS: good\n'
        msg=self.manager.after_decision(newrun['id'],True,True,result)
        self.assertIn('Verification: PASS',msg)
        self.assertEqual(self.manager.store.get(self.task)['status'],'completed')
    def test_denial_stops(self):
        first=self.approvals[0];first['status']='completed'
        with patch('core.jarvis_task_repair.propose_verilog_repair',return_value=('projects/repair_test/design_tb.v',self.tb+'\n')):
            self.manager.after_decision(first['id'],True,True,'Verilog compile FAILED (exit 1):\ndesign_tb.v:1: syntax error')
        item=self.approvals[-1]
        self.manager.after_decision(item['id'],False,False,'Denied')
        self.assertEqual(self.manager.store.get(self.task)['status'],'cancelled')
    def test_limit_no_third_proposal(self):
        plan=self.manager.store.get(self.task)['plan'];plan['_repair_attempts']=2
        self.manager.store.update(self.task,plan=plan)
        first=self.approvals[0]
        self.manager.after_decision(first['id'],True,True,'Verilog compile FAILED (exit 2):\ndesign_tb.v:3: syntax error')
        self.assertEqual(len(self.approvals),1)
        self.assertEqual(self.manager.store.get(self.task)['status'],'failed')
    def test_unrelated_diagnostics_rejected(self):
        with self.assertRaises(RepairError):
            propose_verilog_repair('objective','Verilog compile FAILED (exit 1):\n/tmp/else.v:2: syntax error',
                {'projects/repair_test/design.v':self.rtl,'projects/repair_test/design_tb.v':self.tb},'m','http://localhost')

if __name__=='__main__': unittest.main()
