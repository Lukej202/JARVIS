import sys, tempfile, unittest, subprocess, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from jarvis_task_planner_fixed import make_plan

class PlannerFixTests(unittest.TestCase):
    def test_counter_plan(self):
        plan=make_plan('Create an 8-bit counter in Verilog, write a testbench, simulate it, and verify results.', 'unused','http://127.0.0.1:9')
        self.assertEqual(plan['language'],'verilog')
        self.assertEqual(len(plan['files']),2)
        self.assertEqual(plan['run']['testbench'],'counter_8bit_tb.v')
        self.assertIn('$fatal',plan['files'][1]['content'])
        with tempfile.TemporaryDirectory() as root:
            r=Path(root)
            (r/'projects').mkdir()
            for item in plan['files']:
                (r/item['path']).write_text(item['content'])
            if shutil.which('iverilog') and shutil.which('vvp'):
                c=subprocess.run(['iverilog','-g2012','-s','counter_8bit_tb','-o',str(r/'sim.vvp'),str(r/'counter_8bit.v'),str(r/'counter_8bit_tb.v')],capture_output=True,text=True)
                self.assertEqual(c.returncode,0,c.stderr)
                v=subprocess.run(['vvp','-n',str(r/'sim.vvp')],cwd=r,capture_output=True,text=True,timeout=15)
                self.assertEqual(v.returncode,0,v.stdout+v.stderr)
                self.assertIn('PASS',v.stdout)
    def test_other_tasks_use_model(self):
        from jarvis_task_planner_fixed import _counter_plan
        self.assertIsNone(_counter_plan('Create a Python calculator and test it'))
        self.assertIsNone(_counter_plan('Create a Verilog down counter with testbench'))

if __name__=='__main__': unittest.main()
