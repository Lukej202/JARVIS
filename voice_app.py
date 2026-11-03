from io import BytesIO
from threading import Lock

from flask import Flask, jsonify, render_template_string, request
from faster_whisper import WhisperModel

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB recordings

speech_model = None
model_lock = Lock()


def get_speech_model():
    """Load Whisper once; after the first download it runs locally."""
    global speech_model
    with model_lock:
        if speech_model is None:
            print("JARVIS: Loading local Whisper model...", flush=True)
            speech_model = WhisperModel(
                "base.en", device="cpu", compute_type="int8"
            )
            print("JARVIS: Local speech recognition ready!", flush=True)
    return speech_model


PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>JARVIS Voice</title>
    <style>
        body {
            background: #101820; color: #e7f5ff;
            font-family: Arial, sans-serif; text-align: center;
            padding: 60px 20px;
        }
        h1 { color: #4fc3f7; letter-spacing: 4px; }
        button {
            padding: 14px 25px; margin: 10px; cursor: pointer;
            border-radius: 8px; border: 0; font-size: 15px;
        }
        button:disabled { opacity: 0.5; cursor: not-allowed; }
        audio { display: block; margin: 25px auto; max-width: 100%; }
        #transcript {
            background: #1b2b38; border-radius: 8px;
            padding: 20px; margin: 20px auto;
            max-width: 600px; min-height: 30px;
            overflow-wrap: anywhere;
        }
    </style>
</head>
<body>
    <h1>J.A.R.V.I.S.</h1>
    <p id="status">Local voice system ready.</p>

    <button id="start">Start Recording</button>
    <button id="stop" disabled>Stop Recording</button>
    <button id="speak">Test JARVIS Voice</button>
    <audio id="playback" controls></audio>

    <h3>What JARVIS heard:</h3>
    <p id="transcript">Nothing yet...</p>
    <p>Speech recognition runs locally in Ubuntu WSL.</p>

    <script>
        let recorder;
        let stream;
        let chunks = [];
        let audioUrl = null;

        const start = document.getElementById("start");
        const stop = document.getElementById("stop");
        const status = document.getElementById("status");
        const playback = document.getElementById("playback");
        const transcript = document.getElementById("transcript");


        
document.getElementById("speak").onclick = () => {
    const message = new SpeechSynthesisUtterance(
        "At your service. JARVIS voice system online."
    );

    message.rate = 1.0;
    message.pitch = 0.9;

    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(message);
};

        start.onclick = async () => {
            start.disabled = true;
            transcript.textContent = "Nothing yet...";
            try {
                stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                chunks = [];
                recorder = new MediaRecorder(stream);

                recorder.ondataavailable = event => {
                    if (event.data.size > 0) chunks.push(event.data);
                };

                recorder.onstop = async () => {
                    stream.getTracks().forEach(track => track.stop());
                    stop.disabled = true;
                    status.textContent = "Transcribing locally...";

                    const audio = new Blob(chunks, { type: recorder.mimeType });
                    if (audioUrl) URL.revokeObjectURL(audioUrl);
                    audioUrl = URL.createObjectURL(audio);
                    playback.src = audioUrl;

                    if (audio.size === 0) {
                        status.textContent = "Error: Recording was empty.";
                        start.disabled = false;
                        return;
                    }

                    const formData = new FormData();
                    const filename = audio.type.includes("mp4")
                        ? "recording.mp4" : "recording.webm";
                    formData.append("audio", audio, filename);

                    try {
                        const response = await fetch("/transcribe", {
                            method: "POST", body: formData
                        });
                        const result = await response.json();
                        if (!response.ok) {
                            throw new Error(result.error || "Transcription failed");
                        }
                        transcript.textContent = result.text || "No speech detected.";
                        status.textContent = "Transcription complete!";
                    } catch (error) {
                        status.textContent = "Error: " + error.message;
                        transcript.textContent = "Transcription failed.";
                    } finally {
                        start.disabled = false;
                    }
                };

                recorder.start();
                stop.disabled = false;
                status.textContent = "Listening...";
            } catch (error) {
                status.textContent = "Microphone error: " + error.message;
                start.disabled = false;
                if (stream) stream.getTracks().forEach(track => track.stop());
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
    if audio is None or not audio.filename:
        return jsonify(error="No audio received."), 400

    audio_bytes = audio.read()
    if not audio_bytes:
        return jsonify(error="Empty recording."), 400

    try:
        segments, _ = get_speech_model().transcribe(
            BytesIO(audio_bytes), language="en", beam_size=1
        )
        # Segments is a generator: iterating actually performs transcription.
        text = " ".join(segment.text.strip() for segment in segments).strip()
        print("JARVIS heard:", text, flush=True)
        return jsonify(text=text or "No speech detected.")
    except Exception:
        app.logger.exception("Local transcription failed")
        return jsonify(error="Local transcription failed. Check the terminal."), 500


@app.errorhandler(413)
def recording_too_large(_error):
    return jsonify(error="Recording is too large (10 MB limit)."), 413


if __name__ == "__main__":
    get_speech_model()
    app.run(host="127.0.0.1", port=5000, debug=False)
