"""Install the sequence detector verifier only on the uploaded planner version."""
from pathlib import Path
import hashlib, shutil, datetime, sys
ROOT = Path(__file__).resolve().parent
TARGET = Path.cwd() / 'core' / 'jarvis_task_planner.py'
EXPECTED = "98d2b4cd9eac77caca8a3fbac9d48934b4d42f04c31a2631be1605c3793e4679"

def main():
    if not (Path.cwd() / 'jarvis_core.py').is_file() or not TARGET.is_file():
        sys.exit('Run installer from the root of ~/JARVIS (jarvis_core.py required).')
    current = TARGET.read_bytes()
    if hashlib.sha256(current).hexdigest() != EXPECTED:
        sys.exit('Refusing to overwrite planner: local version differs from uploaded source. No changes made. Upload current planner for a compatible update.')
    incoming = (ROOT / 'jarvis_task_planner.py').read_bytes()
    if not incoming or incoming == current:
        print('Already installed or missing replacement.'); return
    backup_dir = Path.cwd() / 'archive' / 'backups' / ('sequence_repair_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    backup_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(TARGET, backup_dir / TARGET.name)
    tmp=TARGET.with_name(TARGET.name + '.repair_tmp')
    try:
        tmp.write_bytes(incoming)
        tmp.replace(TARGET)
    finally:
        if tmp.exists(): tmp.unlink()
    print('Installed verified sequence-detector planner.')
    print('Previous planner backed up to:', backup_dir)
    print('Existing projects, databases, approvals, and task manager unchanged.')

if __name__ == '__main__': main()
