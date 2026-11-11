# JARVIS Milestone 10 — Live Windows System Monitor

This upgrade extends the *existing* Flask Control Center. It leaves your
unified AI agent, tools, private SQLite memory, voice model, and approval
system alone. **The ZIP contains only:**

- `system_monitor.py` (new, read-only Windows host metrics collector)
- `integrated_voice_app.py` (the previous GUI Flask server with one new endpoint)
- `templates/index.html` (adds a monitor panel)
- `static/style.css` and `static/app.js` (live displays)
- `README_SYSTEM_MONITOR.md` (these instructions)

## 1. Create the branch

Stop Flask with Ctrl+C, then in your Ubuntu WSL VS Code terminal:

```bash
cd ~/JARVIS
git status
git switch -c feature/system-monitor
```

If `feature/system-monitor` already exists, use `git switch feature/system-monitor`
instead. Start from your pushed `feature/gui` branch. If the branch is not
committed / clean yet, commit your GUI files before making a new branch.

## 2. Install from Windows Downloads

Download `JARVIS_M10_System_Monitor.zip` to `C:\Users\lukej\Downloads`.
Use the **WSL terminal** (not Windows drag-and-drop; Explorer previously gave
a write-protection error):

```bash
cd ~/JARVIS
unzip -o /mnt/c/Users/lukej/Downloads/JARVIS_M10_System_Monitor.zip -d ~/JARVIS
```

`unzip` will replace your existing Flask file and GUI files with the upgraded
versions. It does not contain `.env`, `jarvis_core.py`, `jarvis_agent.py`,
`workspace`, or any SQLite databases.

## 3. Verify sensor availability

```bash
source .venv/bin/activate
python -m py_compile system_monitor.py integrated_voice_app.py jarvis_core.py
python system_monitor.py
```

The last command prints one JSON sample. On your Windows 11 + Ubuntu WSL
machine, expected metric fields include `cpu.percent`, `memory.percent`,
`gpu.percent`, and `gpu.temperature_c`. **Values are not hardcoded.**

- CPU and RAM come from **Windows** via PowerShell `Get-CimInstance`.
  The CPU number is a host load estimate, not a high-frequency benchmark.
- NVIDIA GPU usage, VRAM, and temperature come from **Windows** `nvidia-smi.exe`
  when installed and supported by your driver.
- If a sensor isn't accessible, its value is `null` and the GUI displays `—`.
  No WSL CPU/memory values are mislabeled as Windows host metrics.
- The server caches samples for six seconds, and the page requests updates
  about every 7.5 seconds. No API credits or external service required.

If `python system_monitor.py` reports the host unavailable, verify WSL can
launch Windows PowerShell:

```bash
powershell.exe -NoProfile -NonInteractive -Command '$PSVersionTable.PSVersion'
```

To check NVIDIA from Windows, open a Windows PowerShell terminal and run:

```powershell
nvidia-smi.exe --query-gpu=name,utilization.gpu,temperature.gpu,memory.used,memory.total --format=csv,noheader,nounits
```

If it isn't found, locate `nvidia-smi.exe` within your NVIDIA driver
installation. GPU data may be absent with unsupported driver/tool combinations.

## 4. Start and test the dashboard

```bash
python integrated_voice_app.py
```

Visit http://127.0.0.1:5000 in Chrome/Edge and hard refresh with
**Ctrl+Shift+R** if needed. Click **System monitor** in the left navigation.

- CPU and RAM should change as your Windows PC runs applications.
- GPU utilization and GPU temperature should populate if NVIDIA exposes them.
- Test Calculator opening, voice recording, and approval controls to ensure
  the older JARVIS features were not disrupted.
- The **refresh** icon reads the latest cached sample, which may be up to
  six seconds old. The `SAMPLED` time reports when the server collected it.

## 5. Save to GitHub after testing

```bash
git status
git add system_monitor.py integrated_voice_app.py templates/index.html static/style.css static/app.js README_SYSTEM_MONITOR.md
git diff --cached --stat
git diff --cached --check
# Review staged changes for secrets and private files before committing:
git diff --cached
git commit -m "Add live Windows CPU and NVIDIA GPU monitoring"
git push -u origin feature/system-monitor
```

Keep your `.env`, local SQLite databases, `.venv`, and `jarvis_session.lock`
ignored. Flask remains bound to `127.0.0.1`; do not expose this development
server on the public Internet.

For rollback, switch back to the already-pushed `feature/gui` branch and
restart Flask. Your conversation history is left untouched.
