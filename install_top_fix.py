"""Install the focused Verilog simulation-top fix into ~/JARVIS/tools."""
from pathlib import Path
import shutil
import sys
from datetime import datetime

root = Path(__file__).resolve().parent
target = root / 'tools' / 'jarvis_workspace_runner.py'
source = root / 'jarvis_workspace_runner.py'
if not target.is_file():
    sys.exit('ERROR: tools/jarvis_workspace_runner.py not found. No changes made.')
if not source.is_file():
    sys.exit('ERROR: patched runner missing from ZIP. No changes made.')
existing = target.read_text(encoding='utf-8')
if 'def validate_request(' not in existing or 'def execute_approved_program(' not in existing:
    sys.exit('ERROR: Existing runner has unexpected structure. No changes made.')
if 'def _testbench_top(' in existing:
    sys.exit('Top-detection fix appears already installed. No changes made.')
backup_dir = root / 'archive' / 'backups'
backup_dir.mkdir(parents=True, exist_ok=True)
backup = backup_dir / ('jarvis_workspace_runner.pre_top_fix_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.py.bak')
shutil.copy2(target, backup)
shutil.copy2(source, target)
print('Installed:', target)
print('Backup:', backup)
print('Your files, database, and approvals were not modified.')
