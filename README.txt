JARVIS Verified Sequence Detector Repair (v1)

Fixes: deterministic specification-derived overlapping Moore sequence detectors
with active-low reset; independent sliding-window testbenches; refuses known
invalid Verilog ternary/system-task syntax in model-generated testbenches.

This is a focused fix to the demonstrated pattern-detector failure, NOT a
fully general autonomous compiler-driven repair system. Code generation for
other novel Verilog/Python projects still relies on Ollama and can be wrong.

Stop JARVIS, then from WSL:
  cd ~/JARVIS
  unzip -o /mnt/c/Users/lukej/Downloads/JARVIS_Verified_Sequence_Repair.zip -d .
  source .venv/bin/activate
  python -m unittest -v test_sequence_repair.py
  python install_sequence_repair.py
  bash start_jarvis.sh

Test (new project, not an overwrite):
  /task Create a Verilog sequence detector for 1011, write a self-checking
  testbench, simulate it, and verify the results.

Approve execution when JARVIS requests it; the template itself never executes
code. Verification PASS depends on the approved simulation actually passing.

No automatic repair of previous broken projects; no changes to JARVIS
chat/Discord routing or existing task approvals. Installer refuses if local
planner differs from user's uploaded source, with a backup on success.
