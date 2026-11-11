JARVIS SUPERVISED FUNCTIONAL REPAIR V1

New command: /task test-repair-functional
It creates a NEW disposable counter project with deliberately incorrect RTL
(count decrements); the existing self-checking up-counter testbench remains intact.

INSTALL (JARVIS stopped, in ~/JARVIS, following General Repair Compatible Edition):
  unzip -o /mnt/c/Users/lukej/Downloads/JARVIS_Functional_Repair_V1.zip -d .
  source .venv/bin/activate
  python install_functional_repair.py
  python -m unittest -v test_functional_repair.py
  bash start_jarvis.sh

Run /task test-repair-functional. Approve initial simulation. Its testbench
should fail. JARVIS then asks Qwen for a new RTL proposal; you must separately
approve the RTL overwrite and the rerun. Maximum 2 approved repair attempts.

This is an experimental feature, not formally verified synthesis/RTL quality.
It does not modify existing projects, task history, Flask or Discord code.
If the installer rejects your current version, stop and share the current
jarvis_core.py and core/jarvis_task_manager.py; do not force the install.
