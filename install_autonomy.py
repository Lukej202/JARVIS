#!/usr/bin/env python3
"""Safely install JARVIS supervised task v1 into the current repository.

Run from ~/JARVIS after extracting ZIP. Refuses to overwrite a version that
has diverged from the three uploaded files used to build the patch.
"""
from pathlib import Path
from datetime import datetime
import hashlib
import shutil
import sys
import py_compile

BASE = Path(__file__).resolve().parent
PAYLOAD=BASE/'autonomy_payload'
FILES=[
    'jarvis_core.py',
    'discord_bot.py',
    'core/jarvis_task_planner.py',
    'core/jarvis_task_state.py',
    'core/jarvis_task_manager.py',
    'tests/test_supervised_tasks.py',
]
EXPECTED={
    'jarvis_core.py':'7de9181deb83dd6e307961609ac224b4f27d41e6200cc39abf465114e8a26b53',
    'discord_bot.py':'478efc9607d057cb80d237ee2c7a63406123a57b172d0d6322c943eb1d55e853',
}

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    if not (BASE/'tools/jarvis_workspace_runner.py').is_file() or not (BASE/'core/jarvis_output.py').is_file():
        sys.exit('ERROR: Run from your current JARVIS repository with core/ and tools/ already set up.')
    runner=(BASE/'tools/jarvis_workspace_runner.py').read_text()
    if 'def _testbench_top' not in runner or 'def validate_request' not in runner:
        sys.exit('ERROR: Install the working Verilog top-detection fix before autonomy.')
    for name,expected in EXPECTED.items():
        path=BASE/name
        if not path.is_file():sys.exit(f'ERROR: Missing {name}. Nothing changed.')
        if digest(path)!=expected:
            sys.exit(f'ERROR: {name} differs from the uploaded version. Nothing changed. '
                     'Make sure the latest file is supplied for safe integration.')
    for name in FILES:
        src=PAYLOAD/name
        if not src.is_file():sys.exit(f'ERROR: Missing bundle component {name}. Nothing changed.')
        if name not in EXPECTED and (BASE/name).exists():
            sys.exit(f'ERROR: {name} already exists; refusing to overwrite an existing task module.')
    for name in FILES:
        py_compile.compile(str(PAYLOAD/name),doraise=True)
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    backup=BASE/'archive'/'backups'/f'autonomy_v1_{stamp}'
    backup.mkdir(parents=True,exist_ok=False)
    for name in EXPECTED:
        dest=backup/name
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(BASE/name,dest)
    try:
        for name in FILES:
            dest=BASE/name
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(PAYLOAD/name,dest)
        for name in FILES:
            py_compile.compile(str(BASE/name),doraise=True)
    except Exception:
        for name in EXPECTED:shutil.copy2(backup/name,BASE/name)
        for name in FILES:
            if name not in EXPECTED:
                (BASE/name).unlink(missing_ok=True)
        raise
    print('Installed supervised autonomous tasks v1.')
    print('Backups:',backup)
    print('Run: python -m unittest discover -s tests -p test_supervised_tasks.py -v')
    print('Start JARVIS and try: /task create an 8-bit Verilog counter with a testbench and simulate it')

if __name__=='__main__': main()
