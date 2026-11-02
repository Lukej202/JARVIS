"""JARVIS local voice interface: browser microphone -> Whisper -> Ollama agent.

Requires jarvis_agent.py to be import-safe: its interactive loop must be under
`if __name__ == "__main__":`.

This voice entrypoint deliberately exposes only the existing Calculator and
Notepad tools. Other tools need purpose-built approval flows before being
called from a web request.
"""

from io import BytesIO
from pathlib import Path
from threading import Lock

from agents import (
    Agent,
    AsyncOpenAI,
    OpenAIChatCompletionsModel,
    Runner,
    SQLiteSession,
    set_tracing_disabled,
)
from faster_whisper import WhisperModel
from flask import Flask, jsonify, render_template_string, request
from jarvis_agent import open_calculator, open_notepad

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

# All reasoning stays on the local Ollama server. Disable OpenAI tracing.
set_tracing_disabled(True)
local_client = AsyncOpenAI(
    base_url="http://127.0.0.1:11434/v1/",
    api_key="ollama",  # required by the client, ignored by local Ollama
    timeout=90.0,
    max_retries=0,
)

voice_agent = Agent(
    name="JARVIS",
    instructions=(
        "You are JARVIS, a concise, courteous personal desktop assistant. "
        "The user is speaking to you. Use a registered tool when the user "
        "asks to open Notepad or Calculator. You may use both if requested. "
        "You have no other computer control or file tools in this voice mode. "
        "Do not claim you clicked, typed, saved, or verified a window when "
        "you have not actually done so. Reply briefly for spoken playback."
    ),
    model=OpenAIChatCompletionsModel(
        model="qwen3:4b", openai_client=local_client
    ),
    tools=[open_notepad, open_calculator],
)

voice_session = SQLiteSession(
    "jarvis_voice", str(Path(__file__).with_name("jarvis_voice_memory.db"))
)
agent_lock = Lock()  # Prevent simultaneous turns using the same session.
whisper_model = None
whisper_lock = Lock()


def get_whisper_model():
    global whisper_model
    with whisper_lock:
        if whisper_model is None:
            print("JARVIS: Loading local Whisper...", flush=True)
            whisper_model = WhisperModel(
                "base.en", device="cpu", compute_type="int8"
            )
            print("JARVIS: Whisper ready.", flush=True)
    return whisper_model


PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>JARVIS Voice</title>
  <style>
    body { background:#101820; color:#e7f5ff; font-family:Arial,sans-serif;
           text-align:center; padding:56px 20px; }
    h1 { color:#4fc3f7; letter-spacing:4px; }
    button { padding:14px 25px; margin:8px; cursor:pointer;
             border-radius:8px; border:0; font-size:15px; }
    button:disabled { opacity:.5; cursor:not-allowed; }
    audio { display:block; margin:22px auto; max-width:100%; }
    .panel { background:#1b2b38; border-radius:8px; padding:18px;
             max-width:660px; margin:14px auto; min-height:30px;
             overflow-wrap:anywhere; }
    .muted { color:#adc6d7; font-size:14px; }
  </style>
</head>
<body>
  <h1>J.A.R.V.I.S.</h1>
  <p id="status">Local voice interface ready.</p>
  <button id="start">Start Recording</button>
  <button id="stop" disabled>Stop Recording</button>
  <audio id="playback" controls></audio>
  <h3>What JARVIS heard</h3>
  <p class="panel" id="transcript">Nothing yet...</p>
  <h3>JARVIS responds</h3>
  <p class="panel" id="reply">Ready.</p>
  <p class="muted">Voice recognition and reasoning run locally.</p>
  <script>
    let recorder, stream, chunks = [], audioUrl = null;
    const start = document.getElementById("start");
    const stop = document.getElementById("stop");
    const status = document.getElementById("status");
    const playback = document.getElementById("playback");
    const transcript = document.getElementById("transcript");
    const reply = document.getElementById("reply");

    function speak(text) {
      if (!('speechSynthesis' in window)) return;
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = 1.0;
      utterance.pitch = 0.9;
      window.speechSynthesis.speak(utterance);
    }

    start.onclick = async () => {
      start.disabled = true;
      transcript.textContent = "Nothing yet...";
      try {
        window.speechSynthesis?.cancel();
        stream = await navigator.mediaDevices.getUserMedia({audio:true});
        chunks = [];
        recorder = new MediaRecorder(stream);
        recorder.ondataavailable = event => {
          if (event.data.size > 0) chunks.push(event.data);
        };
        recorder.onstop = async () => {
          stream.getTracks().forEach(track => track.stop());
          stop.disabled = true;
          const audio = new Blob(chunks, {type: recorder.mimeType});
          if (audioUrl) URL.revokeObjectURL(audioUrl);
          audioUrl = URL.createObjectURL(audio);
          playback.src = audioUrl;
          if (audio.size === 0) {
            status.textContent = "Recording was empty.";
            start.disabled = false;
            return;
          }
          status.textContent = "Transcribing locally...";
          const form = new FormData();
          const filename = audio.type.includes("mp4") ? "recording.mp4" : "recording.webm";
          form.append("audio", audio, filename);
          try {
            const tr = await fetch("/transcribe", {method:"POST", body:form});
            const t = await tr.json();
            if (!tr.ok) throw new Error(t.error || "Transcription failed");
            transcript.textContent = t.text || "No speech detected.";
            if (!t.text) {
              status.textContent = "No speech detected.";
              return;
            }
            status.textContent = "Asking local JARVIS...";
            const ar = await fetch("/command", {
              method:"POST",
              headers:{"Content-Type":"application/json"},
              body:JSON.stringify({text:t.text})
            });
            const answer = await ar.json();
            if (!ar.ok) throw new Error(answer.error || "JARVIS request failed");
            reply.textContent = answer.reply;
            status.textContent = "Ready.";
            speak(answer.reply);
          } catch (error) {
            status.textContent = "Error: " + error.message;
            reply.textContent = "Check the Flask terminal for details.";
          } finally {
            start.disabled = false;
          }
        };
        recorder.start();
        status.textContent = "Listening...";
        stop.disabled = false;
      } catch (error) {
        status.textContent = "Microphone error: " + error.message;
        if (stream) stream.getTracks().forEach(track => track.stop());
        start.disabled = false;
      }
    };

    stop.onclick = () => {
      if (recorder && recorder.state === "recording") {
        stop.disabled = true;
        recorder.stop();
      }
    };
  </script>
</body>
</html>
"""


@app.get("/")
def home():
    return render_template_string(PAGE)


@app.post("/transcribe")
def transcribe():
    audio = request.files.get("audio")
    if not audio or not audio.filename:
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
    body = request.get_json(silent=True) or {}
    message = body.get("text")
    if not isinstance(message, str) or not message.strip():
        return jsonify(error="No text command received."), 400
    if len(message) > 1000:
        return jsonify(error="Command is too long."), 400
    try:
        with agent_lock:
            result = Runner.run_sync(
                voice_agent, message.strip(), session=voice_session, max_turns=5
            )
        answer = str(result.final_output or "I couldn't complete that request.")
        return jsonify(reply=answer)
    except Exception:
        app.logger.exception("Local JARVIS agent failed")
        return jsonify(error="Local agent failed. Is Ollama running with qwen3:4b?"), 502


@app.errorhandler(413)
def too_large(_error):
    return jsonify(error="Recording exceeds 10 MB."), 413


if __name__ == "__main__":
    get_whisper_model()
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
