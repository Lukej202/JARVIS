"""Install targeted, reversible JARVIS task reporting patch."""
from pathlib import Path
from datetime import datetime
import ast
import shutil

root = Path(__file__).resolve().parent
core = root / 'jarvis_core.py'
manager = root / 'core' / 'jarvis_task_manager.py'
method = root / 'method.txt'
if not all(p.is_file() for p in (core, manager, method)):
    raise SystemExit('Required files missing; extract all ZIP contents into ~/JARVIS.')
c = core.read_text()
m = manager.read_text()
if 'JARVIS_TASK_REPORTING_V1' in c or 'JARVIS_TASK_REPORTING_V1' in m:
    raise SystemExit('Already installed; no changes made.')
needle = '''        _record_outcome(summary, result)
        if task_payload.get('_task_id'):
            task_result = _task_manager().after_decision(action_id, True, status == 'completed', result)
            if task_result:
                return result + "\\n\\n" + task_result
        return result'''
replacement = '''        _record_outcome(summary, result)
        if task_payload.get('_task_id'):
            # JARVIS_TASK_REPORTING_V1: return state-derived task summary.
            task_result = _task_manager().after_decision(action_id, True, status == 'completed', result)
            if task_result:
                return task_result
        return result'''
if c.count(needle) != 1:
    raise SystemExit('Approval handler changed; refusing automatic edit. No files changed.')
start = m.find('    def _apply_run_result(self,task_id,idx,result):')
end = m.find('\n    def after_decision(',start)
if start == -1 or end == -1:
    raise SystemExit('Task manager differs from expected layout; no files changed.')
newc = c.replace(needle,replacement,1)
newm = m[:start]+method.read_text().rstrip()+m[end:]
ast.parse(newc); ast.parse(newm)
backups = root/'archive'/'backups'
backups.mkdir(parents=True,exist_ok=True)
stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
for path in (core,manager):
    shutil.copy2(path,backups/(path.stem+'.before_task_report_'+stamp+'.py.bak'))
core.write_text(newc)
manager.write_text(newm)
print('Installed. Original files backed up in archive/backups/.')
print('Approval rules, SQLite state, and workspace contents were not changed.')
