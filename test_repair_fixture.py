import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from core.jarvis_task_manager import TaskManager

class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'workspace';self.root.mkdir()
        self.actions=[]
        def queue(kind,payload,summary):
            item={'id':f'{len(self.actions)+1:012x}','kind':kind,'payload':payload,'status':'pending'}
            self.actions.append(item);return item['id']
        def lookup(task_id,idx):
            for action in reversed(self.actions):
                if action['kind']=='run_workspace_program' and action['payload'].get('_task_id')==task_id and action['payload'].get('_task_step')==idx:
                    return action['id'],action['status'],action.get('result','')
        self.manager=TaskManager(self.root,store_path=self.root.parent/'tasks.db',approval_lookup=lookup,
                                 queue_approval=queue,model='qwen3.5:4b',ollama_url='http://localhost:11434')

    def test_fixture_is_new_and_requires_approval(self):
        response=self.manager.start_repair_test()
        self.assertIn('deliberately broken',response)
        self.assertEqual(self.actions[0]['kind'],'run_workspace_program')
        task=self.manager.store.active()
        self.assertEqual(task['plan']['language'],'verilog')
        self.assertTrue(task['plan']['_repair_test'])
        self.assertTrue(task['plan']['project'].startswith('repair_demo_'))
        tb=self.root/task['steps'][-1]['testbench']
        text=tb.read_text()
        self.assertIn('        $finish\n',text)
        self.assertNotIn('        $finish;',text)
        self.assertEqual(task['status'],'waiting_approval')
        self.assertEqual(len(list((self.root/'projects').iterdir())),1)

    def test_active_task_blocks_second_fixture(self):
        self.manager.start_repair_test()
        second=self.manager.start_repair_test()
        self.assertIn('Another autonomous task is active',second)
        self.assertEqual(len(self.actions),1)

    def test_first_compile_failure_proposes_repair(self):
        self.manager.start_repair_test()
        task=self.manager.store.active()
        run=self.actions[0]
        tb=task['steps'][-1]['testbench']
        original=(self.root/tb).read_text()
        repaired=original.replace('        $finish\n','        $finish;\n',1)
        with patch('core.jarvis_task_repair.propose_verilog_repair',return_value=(tb,repaired)):
            message=self.manager.after_decision(run['id'],True,True,
               'Verilog compile FAILED (exit 2):\n'+tb+':25: syntax error')
        self.assertIn('awaits overwrite approval',message)
        self.assertEqual(self.actions[-1]['kind'],'write_file')
        self.assertEqual((self.root/tb).read_text(),original)

if __name__=='__main__':unittest.main()
