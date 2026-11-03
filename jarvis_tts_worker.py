"""Persistent Kokoro ONNX worker (run ONLY with the separate Python 3.12 venv).

Protocol: one JSON object per line on stdin; one JSON object per line on
stdout. This keeps the ONNX model in memory between requests while the main
JARVIS Flask app continues to run in its existing Python 3.14 environment.
"""

import base64
from io import BytesIO
import json
import sys


def send(packet):
    print(json.dumps(packet, ensure_ascii=True, separators=(",", ":")), flush=True)


def main():
    if len(sys.argv) != 3:
        send({"event": "error", "error": "Expected ONNX model and voice-pack paths."})
        return 1

    try:
        from kokoro_onnx import Kokoro
        import soundfile as sf
        kokoro = Kokoro(sys.argv[1], sys.argv[2])
    except Exception as exc:
        send({"event": "error", "error": f"Could not load Kokoro: {type(exc).__name__}: {exc}"})
        return 1

    send({"event": "ready"})
    for line in sys.stdin:
        try:
            command = json.loads(line)
            text = command.get("text", "")
            if not isinstance(text, str) or not text.strip() or len(text) > 1300:
                raise ValueError("Text must contain 1 to 1,300 characters.")
            voice = command.get("voice", "bm_lewis")
            if voice != "bm_lewis":
                raise ValueError("Only bm_lewis is enabled for this JARVIS worker.")
            speed = float(command.get("speed", 0.95))
            if not 0.7 <= speed <= 1.2:
                raise ValueError("Voice speed outside the allowed range.")

            samples, sample_rate = kokoro.create(
                text, voice=voice, speed=speed, lang="en-gb"
            )
            output = BytesIO()
            sf.write(output, samples, sample_rate, format="WAV", subtype="PCM_16")
            send({"ok": True, "audio": base64.b64encode(output.getvalue()).decode("ascii")})
        except Exception as exc:
            send({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
