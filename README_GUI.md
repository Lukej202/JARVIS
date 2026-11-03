# JARVIS Control Center — Milestone 9 (GUI v1)

This installs a **local Flask dashboard** on top of the working unified JARVIS core.
It preserves the existing Ollama `qwen3:4b` agent, local Whisper recognition,
Windows tools, action approval queue, and the shared `jarvis_memory.db` history.

## Files in this update

- `jarvis_core.py` — previous unified core **plus** two read-only functions for
  shared conversation/activity history and logging of application-launch attempts.
- `integrated_voice_app.py` — same existing command/transcribe/action routes,
  with added `/history`, `/activity`, `/status` routes; serves separate GUI files.
- `templates/index.html` — dashboard structure and accessible controls.
- `static/style.css` — dark cyan responsive design and animated core.
- `static/app.js` — microphone, chat, speech, approvals, status, and activity.

**Keep unchanged:** `jarvis_agent.py`, `vision_test.py`, `windows_input_test.py`,
`.env`, `.venv/`, `workspace/`, `jarvis_memory.db`, `jarvis_actions.db` and
`jarvis_voice_memory.db`.

## 1. Save your current working milestone

From your **WSL Ubuntu VS Code terminal**:

```bash
cd ~/JARVIS
git status
```

If the unified-core branch has uncommitted code, review, commit and push it
first. Then create the new GUI feature branch:

```bash
git switch -c feature/gui
```

If the branch already exists, use `git switch feature/gui` instead.

## 2. Install using WSL, NOT Windows File Explorer

Because Windows Explorer previously reported that the Ubuntu WSL disk was
write-protected, copy with **Ubuntu `unzip`**, not drag-and-drop. Download
`JARVIS_GUI_M9.zip` into the Windows Downloads folder, then run:

```bash
cd ~/JARVIS
unzip -o /mnt/c/Users/lukej/Downloads/JARVIS_GUI_M9.zip -d ~/JARVIS
```

If you see `unzip: command not found`, install it via `sudo apt install unzip`.
The archive contains only the five files listed above; no personal settings,
virtual environments, or memory databases are overwritten.

Check that the new structure exists:

```text
JARVIS/
├── jarvis_core.py
├── jarvis_agent.py              # unchanged
├── integrated_voice_app.py
├── templates/
│   └── index.html
├── static/
│   ├── style.css
│   └── app.js
└── ... existing project files ...
```

## 3. Check and run

Make sure **Ollama is running** and `qwen3:4b` appears in `ollama list`.

```bash
cd ~/JARVIS
source .venv/bin/activate
python -m py_compile jarvis_core.py jarvis_agent.py integrated_voice_app.py
python integrated_voice_app.py
```

Open **http://127.0.0.1:5000** in Windows Chrome or Edge. If the previous page
still appears, press `Ctrl+Shift+R` to refresh the browser.

## 4. Test the GUI in order

1. Check whether the sidebar reports **Ollama: Online** and **Whisper: Ready**.
2. Type **"Open Calculator"** in chat. Calculator should launch; its launch
   attempt should appear in the recent activity list.
3. Speak **"What was my favorite test number?"** after clicking **Start
   listening**, then **Stop**; voice playback should still work.
4. Type **"Create a file called gui_test.txt that says GUI is working"**.
   Confirm the request appears in **Action approvals**, review it, and approve
   or deny it. It must not create the file until approved.
5. Run `python jarvis_agent.py` in a second WSL terminal and check that both
   interfaces continue sharing conversation history.

## Notes / limits

- The animated orb follows microphone, transcription, model-processing, and
  browser speech events. It is **not** a true audio waveform visualizer yet.
- Activity includes requests for opening apps and actions recorded in the
  approval database. It doesn't log every model inference or every OS action.
- The sidebar reports Ollama model availability, whether Whisper has been
  loaded, Windows Calculator command availability, and optional vision model
  installation. It does **not** measure GPU/CPU utilization yet.
- The browser uses built-in `speechSynthesis` for spoken replies. More natural
  voices and live waveform visualization are future upgrades.
- Flask is bound to **127.0.0.1** for local use. Do not expose this development
  server to public networks or disable approval protections.
- The personal conversation and action history remain on disk in the existing
  SQLite databases, which must stay **excluded from Git**.
- If you need to roll back, switch back to your previous Git branch and restart
  Flask. Your preexisting memory databases remain untouched.

## Commit the milestone after testing

```bash
git status
git add jarvis_core.py integrated_voice_app.py templates/index.html static/style.css static/app.js README_GUI.md
git diff --cached --stat
git diff --cached --check
git commit -m "Build JARVIS local control center GUI"
git push -u origin feature/gui
```
