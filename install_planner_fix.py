"""Install planner-only patch; do not alter runtime, approval, or memory files."""
from datetime import datetime
from pathlib import Path
import shutil

root = Path(__file__).resolve().parent
source = root / 'jarvis_task_planner_fixed.py'
target = root / 'core' / 'jarvis_task_planner.py'
if not target.is_file():
    raise SystemExit('Missing core/jarvis_task_planner.py. Install autonomous tasks v1 first.')
if not source.is_file():
    raise SystemExit('Missing jarvis_task_planner_fixed.py; extract the complete ZIP.')
backup_dir = root / 'archive' / 'backups'
backup_dir.mkdir(parents=True, exist_ok=True)
backup = backup_dir / ('jarvis_task_planner.before_fix_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.py.bak')
shutil.copy2(target, backup)
shutil.copy2(source, target)
print('Updated:', target)
print('Backup:', backup)
print('No database, task state, workspace file, or approval rule changed.')
