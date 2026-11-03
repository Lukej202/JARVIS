"""JARVIS Control Center: local Flask GUI for the shared Ollama agent.

Keeps the existing voice, memory, tool and approval behavior; HTML/CSS/JS
live under templates/ and static/ to make future GUI work maintainable.
"""
from io import BytesIO
import atexit
import base64
import os
import re
import select
import subprocess
import time
import json
from pathlib import Path
import secrets
import shutil
from threading import Lock
from urllib.error import URLError
from urllib.request import urlopen

from faster_whisper import WhisperModel
from flask import Flask, Response, jsonify, render_template, request

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

# Kokoro is installed in its own Python 3.12 environment. Keep a single local
# worker alive so the ONNX voice model does NOT reload for every response.
_TTS_PYTHON = Path(os.getenv(
    "JARVIS_TTS_PYTHON", str(Path.home() / ".venvs/jarvis-tts/bin/python")
)).expanduser()
_TTS_MODEL = ROOT / "tts_models" / "kokoro-v1.0.onnx"
_TTS_VOICES = ROOT / "tts_models" / "voices-v1.0.bin"
_tts_lock = Lock()
_tts_process = None
_tts_buffer = b""


def _stop_tts_worker():
    global _tts_process, _tts_buffer
    process = _tts_process
    _tts_process = None
    _tts_buffer = b""
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


atexit.register(_stop_tts_worker)


def _read_tts_packet(process, timeout=120):
    """Read one JSON-line response, with a hard timeout and size limit."""
    global _tts_buffer
    deadline = time.monotonic() + timeout
    while True:
        if b"\n" in _tts_buffer:
            raw_line, _tts_buffer = _tts_buffer.split(b"\n", 1)
            try:
                packet = json.loads(raw_line)
                if isinstance(packet, dict):
                    return packet
            except (ValueError, UnicodeError):
                # A dependency printed a diagnostic to stdout; ignore the line.
                pass
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Kokoro did not respond in time.")
        ready, _, _ = select.select([process.stdout], [], [], min(remaining, 1.0))
        if not ready:
            if process.poll() is not None:
                raise RuntimeError("Kokoro worker exited unexpectedly; check the Flask terminal.")
            continue
        chunk = os.read(process.stdout.fileno(), 64 * 1024)
        if not chunk:
            raise RuntimeError("Kokoro worker closed its output stream.")
        _tts_buffer += chunk
        if len(_tts_buffer) > 24 * 1024 * 1024:
            raise ValueError("Kokoro returned an unexpectedly large response.")


def _ensure_tts_worker():
    global _tts_process, _tts_buffer
    if _tts_process is not None and _tts_process.poll() is None:
        return _tts_process
    if not _TTS_PYTHON.is_file():
        raise FileNotFoundError(f"Voice Python is missing: {_TTS_PYTHON}")
    for path in (_TTS_MODEL, _TTS_VOICES):
        if not path.is_file():
            raise FileNotFoundError(f"Kokoro model file is missing: {path}")
    _tts_buffer = b""
    _tts_process = subprocess.Popen(
        [str(_TTS_PYTHON), "-u", str(ROOT / "jarvis_tts_worker.py"),
         str(_TTS_MODEL), str(_TTS_VOICES)],
        cwd=str(ROOT), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=None,  # Errors appear in the existing Flask terminal.
    )
    packet = _read_tts_packet(_tts_process, timeout=90)
    if packet.get("event") != "ready":
        raise RuntimeError(packet.get("error", "Unexpected Kokoro startup response."))
    print("JARVIS: Kokoro ready (bm_lewis).", flush=True)
    return _tts_process


def _make_speech_wav(text):
    """Generate audio using the persistent local Kokoro worker."""
    with _tts_lock:
        try:
            process = _ensure_tts_worker()
            command = json.dumps({"text": text, "voice": "bm_lewis", "speed": 0.95})
            process.stdin.write(command.encode("utf-8") + b"\n")
            process.stdin.flush()
            result = _read_tts_packet(process, timeout=120)
            if not result.get("ok"):
                raise RuntimeError(result.get("error", "Kokoro voice generation failed."))
            return base64.b64decode(result["audio"], validate=True)
        except (OSError, ValueError, TimeoutError, RuntimeError, KeyError) as exc:
            _stop_tts_worker()  # Clean restart on the next request.
            raise RuntimeError(str(exc)) from exc


def _prepare_spoken_text(text):
    """Remove common Markdown/URLs so JARVIS doesn't read formatting aloud."""
    text = re.sub(r"```[\s\S]*?```", " Code block omitted. ", text)
    text = re.sub(r"\[([^\]]+)\]\(https?://[^\s)]+\)", r"\1", text)
    text = re.sub(r"https?://[^\s]+", "a link", text)
    text = re.sub(r"[`*_#|]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1200]


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
        return jsonify(error=f"Local JARVIS failed. Is Ollama running with {MODEL_NAME}?"), 502


@app.post("/tts")
def synthesize_speech():
    """Authenticated local speech synthesis; returns WAV for the browser."""
    if not _check_local_token():
        return jsonify(error="Unauthorized local request."), 403
    data = request.get_json(silent=True) or {}
    raw_text = data.get("text")
    if not isinstance(raw_text, str) or not raw_text.strip():
        return jsonify(error="No speech text received."), 400
    if len(raw_text) > 6000:
        return jsonify(error="Speech text is too long."), 400
    text = _prepare_spoken_text(raw_text)
    if not text:
        return jsonify(error="Nothing suitable to speak."), 400
    try:
        audio = _make_speech_wav(text)
        return Response(audio, mimetype="audio/wav", headers={
            "Content-Disposition": "inline; filename=jarvis-lewis.wav"
        })
    except Exception:
        app.logger.exception("Local Kokoro speech generation failed")
        return jsonify(error="Kokoro unavailable; use browser voice fallback."), 503


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


# M13_BROWSER_CONTROL: stop button does not wait for conversation/session locks.
@app.post("/browser-stop")
def browser_stop():
    if not _check_local_token():
        return jsonify(error="Unauthorized local request."), 403
    from jarvis_extension_bridge import request_stop
    return jsonify(message=request_stop())


# CHROME_EXTENSION_BRIDGE: independent read-only research lane for paired extension.
# These endpoints never expose the GUI token, pairing key, or personal tabs.
def _extension_authorized():
    from jarvis_extension_bridge import verify_key
    return verify_key(request.headers.get("X-JARVIS-Extension-Key", ""))


@app.get("/extension/health")
def extension_health():
    if not _extension_authorized():
        return jsonify(error="Invalid extension pairing key."), 403
    from jarvis_extension_bridge import heartbeat
    heartbeat()
    return jsonify(ready=True)


@app.get("/extension/next")
def extension_next():
    if not _extension_authorized():
        return jsonify(error="Invalid extension pairing key."), 403
    from jarvis_extension_bridge import claim_next
    return jsonify(job=claim_next())


@app.get("/extension/cancel/<job_id>")
def extension_cancel(job_id):
    if not _extension_authorized():
        return jsonify(error="Invalid extension pairing key."), 403
    from jarvis_extension_bridge import is_cancelled
    return jsonify(cancelled=is_cancelled(job_id))


@app.post("/extension/result")
def extension_result():
    if not _extension_authorized():
        return jsonify(error="Invalid extension pairing key."), 403
    from jarvis_extension_bridge import receive_result
    body = request.get_json(silent=True) or {}
    try:
        accepted = receive_result(body)
        return jsonify(accepted=accepted)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400


@app.errorhandler(413)
def too_large(_error):
    return jsonify(error="Recording exceeds 10 MB."), 413


if __name__ == "__main__":
    get_whisper_model()
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
