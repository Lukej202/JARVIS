JARVIS General Repair Test Commands — compatibility edition

Built from your uploaded jarvis_current_sources.zip.

New commands:
  /task test-repair-port    -> testbench with incorrect named port
  /task test-repair-signal  -> RTL with undeclared signal
Existing /task test-repair remains available.

Only jarvis_core.py and core/jarvis_task_manager.py are changed.

Installation from ~/JARVIS after stopping JARVIS:
  unzip -o /mnt/c/Users/lukej/Downloads/JARVIS_General_Repair_Compatible.zip -d .
  source .venv/bin/activate
  python install_general_repair_compatible.py
  python -m unittest -v test_general_repair_tests.py
  bash start_jarvis.sh

These are deliberately broken, disposable projects. You must still approve
execution, repair overwrites, and reruns separately. Two repair attempts max.
Test commands are diagnostic; model-generated corrections are not guaranteed.
