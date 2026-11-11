JARVIS Compiler Repair Proposal Fix v1.1

This targeted patch changes ONLY core/jarvis_task_repair.py.
- Known missing standalone $finish semicolon near actual compiler diagnostics: propose minimal repair without asking the model.
- Other compile errors: retry one invalid/unchanged model proposal with stricter instructions.
- Never overwrite source or execute a program here; existing approval flow remains mandatory.
- Never silently accept an unchanged repair or wrong filename.
- Existing failed tasks remain in history; run /task test-repair to create a fresh disposable task.

Install (stop JARVIS first):
  cd ~/JARVIS
  unzip -o /mnt/c/Users/lukej/Downloads/JARVIS_Repair_Proposal_Fix_V1_1.zip -d .
  source .venv/bin/activate
  python install_repair_validation.py
  python -m unittest -v test_repair_validation.py
  bash start_jarvis.sh

If installation refuses a checksum mismatch, do not force overwrite: provide the current core/jarvis_task_repair.py.
