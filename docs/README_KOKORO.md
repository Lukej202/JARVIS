# JARVIS — Kokoro `bm_lewis` voice integration

This upgrade replaces Chrome's `speechSynthesis` as the primary JARVIS spoken response, using local Kokoro ONNX. Browser speech remains the fallback if Kokoro is unavailable.

## Included files

- `integrated_voice_app.py` — existing Flask endpoints plus authenticated `POST /tts`, using a persistent Kokoro subprocess
- `jarvis_tts_worker.py` — runs in your separate Python 3.12 environment, loads Kokoro once, generates WAV audio
- `static/app.js` — requests and plays local WAV after every JARVIS response; keeps mute button, core speaking animation, and fallback

**Intentionally unchanged:** `jarvis_core.py`, SQLite memory files, Whisper voice recognition, Chrome tools, `templates/index.html`, CSS, system monitoring, `.env`.

## Prerequisites

You previously created a Kokoro Python 3.12 venv and tested voice WAV samples. Confirm you still have:

```bash
ls -l ~/.venvs/jarvis-tts/bin/python
ls -lh ~/JARVIS/tts_models/kokoro-v1.0.onnx ~/JARVIS/tts_models/voices-v1.0.bin
~/.venvs/jarvis-tts/bin/python -c 'import kokoro_onnx, soundfile; print("Kokoro OK")'
```

If your 3.12 interpreter is elsewhere, set `JARVIS_TTS_PYTHON` to its absolute path before launching Flask.

## Install

1. Stop the currently running Flask server (`Ctrl+C`).
2. From Ubuntu WSL, take a quick backup of the two files we are updating:

```bash
cd ~/JARVIS
cp integrated_voice_app.py integrated_voice_app_before_kokoro.py
cp static/app.js static/app_before_kokoro.js
```

3. Download `JARVIS_Kokoro_Integration.zip` to the Windows Downloads folder and install with:

```bash
unzip -o /mnt/c/Users/lukej/Downloads/JARVIS_Kokoro_Integration.zip -d ~/JARVIS
source .venv/bin/activate
python -m py_compile integrated_voice_app.py jarvis_tts_worker.py
python integrated_voice_app.py
```

4. Open `http://127.0.0.1:5000/` and refresh with `Ctrl+Shift+R` to clear cached JavaScript.
5. Try: **"Jarvis, say good evening and introduce yourself in one sentence."**
6. Watch the Flask terminal for `JARVIS: Kokoro ready (bm_lewis).` on the first reply.

First voice response loads the ONNX model and may be slower; subsequent replies reuse the model. The GUI's speaker toggle still mutes audio. New commands or recording cancel any currently playing reply.

## Fallback & troubleshooting

If Kokoro isn't available, JARVIS should show a toast and speak using the original browser voice. The Flask terminal logs the root cause. Common issues:

- Missing Python 3.12 environment: confirm `~/.venvs/jarvis-tts/bin/python` exists.
- Missing libraries in the TTS environment: run `~/.local/bin/uv pip install --python ~/.venvs/jarvis-tts/bin/python kokoro-onnx soundfile`.
- Missing model files: confirm both `.onnx` and `.bin` files are in `~/JARVIS/tts_models/`.
- No audio from the browser: Chrome may require a user interaction for playback; click Send or Start Listening once.
- Seeing only the old browser voice: check Flask output for `Local Kokoro speech generation failed` and hard-refresh the JARVIS GUI.

The Flask server runs on `127.0.0.1:5000`, and the `/tts` endpoint uses the existing secret `X-JARVIS-Token`. Generated speech stays on your computer.

## Git housekeeping

Avoid committing large model binaries or sample recordings. Add these entries to `.gitignore` if missing:

```gitignore
tts_models/
tts_samples/
integrated_voice_app_before_kokoro.py
static/app_before_kokoro.js
```

After testing, stage only the intended files:

```bash
git status -sb
git add integrated_voice_app.py jarvis_tts_worker.py static/app.js README_KOKORO.md .gitignore
git diff --cached --check
git diff --cached --stat
# Inspect staged changes and then commit/push your development branch.
```
