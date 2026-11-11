"""Replace only the isolated autonomous planner, with a reversible backup."""
from pathlib import Path
from datetime import datetime
import ast, shutil
root=Path(__file__).resolve().parent
source=root/'jarvis_task_planner_v2.py'
target=root/'core'/'jarvis_task_planner.py'
if not target.is_file() or not source.is_file():
    raise SystemExit('Missing core/jarvis_task_planner.py or patch payload; unzip in ~/JARVIS.')
old=target.read_text(encoding='utf-8'); new=source.read_text(encoding='utf-8')
if 'def make_plan(' not in old or 'def _counter_plan(' not in old:
    raise SystemExit('Unexpected planner version: refusing to replace it.')
ast.parse(new)
if old==new:
    print('Staged planner is already installed; no changes made.');raise SystemExit(0)
folder=root/'archive'/'backups';folder.mkdir(parents=True,exist_ok=True)
backup=folder/('jarvis_task_planner.before_staged_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.py.bak')
shutil.copy2(target,backup)
shutil.copy2(source,target)
print('Installed staged planner v2. Previous version backed up at:',backup)
print('No changes to approval rules, task manager, databases or workspace files.')
