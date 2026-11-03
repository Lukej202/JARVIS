"""JARVIS Control Center: local Flask GUI for the shared Ollama agent.

Keeps the existing voice, memory, tool and approval behavior; HTML/CSS/JS
live under templates/ and static/ to make future GUI work maintainable.
"""
from io import BytesIO
import json
from pathlib import Path
import secrets
import shutil
from threading import Lock
from urllib.error import URLError
from urllib.request import urlopen

from faster_whisper import WhisperModel
from flask import Flask, jsonify, render_template, request

from system_monitor import get_system_metrics

from jarvis_core import (
    MODEL_NAME, VISION_MODEL, decide_action, pending_actions,
    recent_actions, recent_messages, run_turn,
)

ROOT = Path(__file__).resolve().parent
app = Flask(__name__, template_folder=str(ROOT / "templates"),
            static_folder=str(ROOT / "static"))
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
TOKEN = secrets.token_urlsafe(32)
_whisper = None
_whisper_lock = Lock()


def get_whisper_model():
    global _whisper
    with _whisper_lock:
        if _whisper is None:
            print("JARVIS: Loading local Whisper...", flush=True)
            _whisper = WhisperModel("base.en", device="cpu", compute_type="int8")
            print("JARVIS: Whisper ready.", flush=True)
    return _whisper


def _check_local_token():
    return secrets.compare_digest(request.headers.get("X-JARVIS-Token", ""), TOKEN)


@app.after_request
def response_headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.get("/")
def home():
    return render_template("index.html", token=TOKEN)


@app.get("/status")
def status():
    if not _check_local_token():
        return jsonify(error="Unauthorized local request."), 403
    ollama_online = False
    model_ready = False
    vision_ready = False
    try:
        with urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as res:
            data = json.load(res)
        ollama_online = True
        names = {model.get("name", "") for model in data.get("models", [])}
        model_ready = MODEL_NAME in names
        vision_ready = VISION_MODEL in names
    except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        pass
    return jsonify(
        ollama="ready" if model_ready else ("model_missing" if ollama_online else "offline"),
        model=MODEL_NAME,
        vision="ready" if vision_ready else "not_installed",
        whisper="ready" if _whisper is not None else "standby",
        windows="ready" if shutil.which("calc.exe") else "unknown",
    )


@app.get("/history")
def history():
    if not _check_local_token():
        return jsonify(error="Unauthorized local request."), 403
    try:
        return jsonify(messages=recent_messages())
    except Exception:
        app.logger.exception("Could not read shared conversation history")
        return jsonify(error="Could not load conversation history."), 500


@app.get("/system-metrics")
def system_metrics():
    # Read-only monitoring endpoint. Uses the same local-session token as chat.
    if not _check_local_token():
        return jsonify(error="Unauthorized local request."), 403
    return jsonify(get_system_metrics())


@app.get("/activity")
def activity():
    if not _check_local_token():
        return jsonify(error="Unauthorized local request."), 403
    return jsonify(actions=recent_actions())


@app.post("/transcribe")
def transcribe():
    if not _check_local_token():
        return jsonify(error="Unauthorized local request."), 403
    audio = request.files.get("audio")
    if audio is None or not audio.filename:
        return jsonify(error="No audio received."), 400
    audio_bytes = audio.read()
    if not audio_bytes:
        return jsonify(error="Empty recording."), 400
    try:
        segments, _ = get_whisper_model().transcribe(
            BytesIO(audio_bytes), language="en", beam_size=1, vad_filter=True
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        print("JARVIS heard:", text, flush=True)
        return jsonify(text=text)
    except Exception:
        app.logger.exception("Local transcription failed")
        return jsonify(error="Local transcription failed. Check terminal."), 500


@app.post("/command")
def command():
    if not _check_local_token():
        return jsonify(error="Unauthorized local request."), 403
    message = (request.get_json(silent=True) or {}).get("text")
    if not isinstance(message, str) or not message.strip():
        return jsonify(error="No text command received."), 400
    try:
        return jsonify(reply=run_turn(message))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except Exception:
        app.logger.exception("Local JARVIS agent failed")
        return jsonify(error="Local JARVIS failed. Is Ollama running with qwen3:4b?"), 502


@app.get("/pending")
def pending():
    if not _check_local_token():
        return jsonify(error="Unauthorized local request."), 403
    return jsonify(actions=pending_actions())


@app.post("/action")
def action():
    if not _check_local_token():
        return jsonify(error="Unauthorized local request."), 403
    data = request.get_json(silent=True) or {}
    action_id = data.get("id")
    approved = data.get("approved")
    if not isinstance(action_id, str) or not isinstance(approved, bool):
        return jsonify(error="Invalid approval."), 400
    try:
        return jsonify(reply=decide_action(action_id, approved))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except Exception:
        app.logger.exception("Action approval failed")
        return jsonify(error="Action failed. Check terminal."), 500


@app.errorhandler(413)
def too_large(_error):
    return jsonify(error="Recording exceeds 10 MB."), 413


if __name__ == "__main__":
    get_whisper_model()
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
