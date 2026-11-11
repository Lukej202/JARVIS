"""Start the local JARVIS Flask dashboard and Discord bot together.

Requires a running local Ollama service; never prints or handles bot credentials.
Run via: bash start_jarvis.sh
"""
from __future__ import annotations

import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent
SERVICES = (
    ("FLASK", "integrated_voice_app.py"),
    ("DISCORD", "discord_bot.py"),
)
STOP = threading.Event()


def check_ollama() -> None:
    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=1.5):
            print("[LAUNCHER] Ollama detected on 127.0.0.1:11434", flush=True)
    except OSError:
        print("[LAUNCHER] WARNING: Ollama is not reachable at 127.0.0.1:11434."
              " Start Ollama separately if JARVIS cannot respond.", flush=True)


def forward_log(label: str, process: subprocess.Popen) -> None:
    assert process.stdout is not None
    try:
        for line in process.stdout:
            print(f"[{label}] {line.rstrip()}", flush=True)
    except (OSError, ValueError):
        pass


def stop_all(processes: list[tuple[str, subprocess.Popen]]) -> None:
    print("[LAUNCHER] Stopping JARVIS services...", flush=True)
    for name, proc in processes:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + 8
    for name, proc in processes:
        if proc.poll() is None:
            try:
                proc.wait(timeout=max(0.05, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                print(f"[LAUNCHER] Force-stopping {name}...", flush=True)
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
    print("[LAUNCHER] Stopped.", flush=True)


def main() -> int:
    missing = [filename for _, filename in SERVICES if not (ROOT / filename).is_file()]
    if missing:
        print(f"[LAUNCHER] Missing project files: {', '.join(missing)}", file=sys.stderr)
        return 1
    check_ollama()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda _signum, _frame: STOP.set())
    processes: list[tuple[str, subprocess.Popen]] = []
    log_threads: list[threading.Thread] = []
    try:
        for name, filename in SERVICES:
            proc = subprocess.Popen(
                [sys.executable, "-u", str(ROOT / filename)],
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            processes.append((name, proc))
            reader = threading.Thread(target=forward_log, args=(name, proc), daemon=True)
            reader.start()
            log_threads.append(reader)
            print(f"[LAUNCHER] Started {name} (PID {proc.pid})", flush=True)
        print("[LAUNCHER] Both services launched. Press Ctrl+C to stop both.", flush=True)
        while not STOP.wait(0.5):
            for name, proc in processes:
                return_code = proc.poll()
                if return_code is not None:
                    print(f"[LAUNCHER] {name} exited (code {return_code}). "
                          "Stopping the other service.", flush=True)
                    return 1
        return 0
    finally:
        stop_all(processes)
        for reader in log_threads:
            reader.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
