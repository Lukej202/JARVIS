#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$(realpath "$0")")"
if [[ ! -x .venv/bin/python ]]; then
  echo "[LAUNCHER] Missing .venv/bin/python. Create or repair your project virtual environment first." >&2
  exit 1
fi
exec .venv/bin/python -u jarvis_launcher.py
