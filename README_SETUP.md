# JARVIS — unified local core (Milestone 8)

This update combines the previous text and voice agents into **one** Ollama-powered
agent with the existing `jarvis_memory.db` / `jarvis_main` SQLite session.

## Files to replace or add

- **Add** `jarvis_core.py` (shared brain/tools/session/approvals)
- **Replace** `jarvis_agent.py` (terminal entry point)
- **Replace** `integrated_voice_app.py` (local voice + text browser entry point)
- **Keep unchanged** `vision_test.py`, `windows_input_test.py`, `.env`, `.venv/`,
  `workspace/` and the SQLite memory database.

**Back up your originals first.** Both `jarvis_agent.py` and
`integrated_voice_app.py` will be replaced. Make changes on your `feature/voice`
branch (or on a new `feature/unified-core` branch).

## Install (from `~/JARVIS` in WSL)

```bash
source .venv/bin/activate
python -m pip install flask openai-agents faster-whisper 'av==18.1.0'
python -m py_compile jarvis_core.py jarvis_agent.py integrated_voice_app.py
ollama list
```

Ollama needs `qwen3:4b`. If not listed:

```bash
ollama pull qwen3:4b
```

The shared core uses only the local Ollama endpoint at `127.0.0.1:11434`.
API credentials in `.env` are not needed for this version.

## Launch one or both interfaces

Terminal:

```bash
python jarvis_agent.py
```

Voice/browser (another WSL terminal):

```bash
python integrated_voice_app.py
```

Open **http://127.0.0.1:5000** in regular Chrome or Edge on Windows.
Keep the Flask server bound to localhost only; it is a development server.

Both interfaces share the original terminal conversation history in
`jarvis_memory.db` using the same session ID `jarvis_main`.
Old *voice-only* history in `jarvis_voice_memory.db` is **not merged**;
leave that file intact as a backup. Do not delete either database.

## Actions, approvals, and boundaries

- Opening Notepad, Calculator and VS Code requires no additional approval.
- Read/list/search operations are limited to `~/JARVIS/workspace` in WSL.
- Create/write/overwrite, paste to Notepad and screen capture only **queue**
  actions. They do not execute until you approve individually.
- To approve in the terminal: `/pending`, then `/approve ACTION_ID` or
  `/deny ACTION_ID`.
- To approve in Chrome/Edge: use the **Actions awaiting approval** panel.
- The browser displays the full file content proposed for writing/pasting.
- File deletion, arbitrary shell commands and unrestricted mouse control are
  intentionally unavailable.
- Approved Notepad automation uses the existing `paste_into_notepad()` helper.
  It can paste into a wrong window if Windows focus changes: verify the target
  and close Notepad tabs with important unsaved work first.
- Screenshot analysis happens **locally**, but needs an **additional** Ollama
  vision-capable model; install it only when you want screen inspection:

```bash
ollama pull gemma3:4b
```

Images are captured only after you approve and are sent to the **local**
Ollama vision API, not a hosted API. The local model may misread tiny text.

## Check in Git without exposing private data

Ensure `.gitignore` excludes these files before committing:

```gitignore
.env
.venv/
workspace/
jarvis_memory.db*
jarvis_voice_memory.db*
jarvis_actions.db*
jarvis_session.lock
__pycache__/
```

Then inspect staged files before committing:

```bash
git status
git add jarvis_core.py jarvis_agent.py integrated_voice_app.py README_SETUP.md .gitignore
git diff --cached --name-only
git commit -m "Unify local JARVIS voice, text, memory, and tools"
```

**Note:** We have syntax-tested these files here, but cannot test your running
Windows UI, Ollama service, or your local helper files from this environment.
Start by testing `open Calculator`, then a cross-interface memory question,
then an approved file creation, before enabling screen inspection.
