"""JARVIS hands-free voice client for Windows Python 3.12.

Says 'Yes, sir?' through the user's *existing* local Flask /tts endpoint
when openWakeWord hears 'Hey Jarvis'. Captures one command, uploads in-memory
WAV to /transcribe, sends text to /command, plays the reply using /tts,
then rearms wake-word detection.

Requirements: pip install openwakeword==0.6.0 sounddevice requests numpy
Requires local JARVIS Flask dashboard running on 127.0.0.1:5000 (WSL).
No files containing audio or the local authentication token are written.
Ctrl+C exits; no requests are automatically approved.
"""

from __future__ import annotations

import argparse
from collections import deque
from html.parser import HTMLParser
from io import BytesIO
import queue
import re
import time
import wave
import winsound
import textwrap

import numpy as np
import requests
import sounddevice as sd
from openwakeword.model import Model

SAMPLE_RATE = 16000
FRAME_SAMPLES = 1280  # 80ms at 16kHz
BASE = "http://127.0.0.1:5000"


class _TokenParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.token: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag.lower() != "meta":
            return
        values = dict(attrs)
        if values.get("name", "").lower() == "jarvis-token":
            self.token = values.get("content") or None


class JarvisAPI:
    """Connects only to the existing localhost Flask server."""

    def __init__(self):
        self.session = requests.Session()
        self.session.trust_env = False  # Do not proxy the localhost token/audio.
        self.headers: dict[str, str] = {}
        self.refresh_token()

    def refresh_token(self):
        try:
            response = self.session.get(BASE + "/", timeout=(3, 8))
            response.raise_for_status()
            parser = _TokenParser()
            parser.feed(response.text)
            if not parser.token:
                raise RuntimeError(
                    "The dashboard did not include its expected jarvis-token meta tag."
                )
            self.headers = {"X-JARVIS-Token": parser.token}
        except requests.RequestException as err:
            raise RuntimeError(
                "Cannot reach JARVIS at 127.0.0.1:5000. "
                "Start integrated_voice_app.py in WSL and refresh the dashboard."
            ) from err

    def _post(self, path: str, *, json_data=None, files=None, timeout=60):
        response = self.session.post(
            BASE + path,
            headers=self.headers,
            json=json_data,
            files=files,
            timeout=(3, timeout),
        )
        if response.status_code == 403:
            # Flask restarts regenerate this session token. Retry once.
            self.refresh_token()
            response = self.session.post(
                BASE + path,
                headers=self.headers,
                json=json_data,
                files=files,
                timeout=(3, timeout),
            )
        if not response.ok:
            try:
                details = response.json().get("error", "Unknown error")
            except ValueError:
                details = response.text[:250]
            raise RuntimeError(f"JARVIS {path} returned HTTP {response.status_code}: {details}")
        return response

    def speak(self, text: str) -> None:
    	# winsound.PlaySound is synchronous by default.
    	# No microphone is open during speech.
    	response = self._post(
        	"/tts",
        	json_data={"text": text[:1000]},
        	timeout=150
    	)

    	if "audio/wav" not in response.headers.get(
        	"content-type", ""
    	).lower():
        	raise RuntimeError(
            	"The JARVIS /tts response was not WAV audio."
        	)

    	winsound.PlaySound(
        	response.content,
       		winsound.SND_MEMORY
    	)


    def transcribe(self, wav_data: bytes) -> str:
        response = self._post(
            "/transcribe",
            files={"audio": ("jarvis-command.wav", wav_data, "audio/wav")},
            timeout=120,
        )
        return str(response.json().get("text", "")).strip()

    def ask(self, command: str) -> str:
        response = self._post("/command", json_data={"text": command}, timeout=150)
        return str(response.json().get("reply", "")).strip()


def _make_audio_queue():
    frames: queue.Queue[bytes] = queue.Queue(maxsize=45)

    def callback(indata, frame_count, time_info, status):
        if status:
            # The audio loop will recover; callback must remain nonblocking.
            pass
        try:
            frames.put_nowait(bytes(indata))
        except queue.Full:
            try:
                frames.get_nowait()  # Drop stale audio rather than blocking capture.
                frames.put_nowait(bytes(indata))
            except queue.Empty:
                pass

    return frames, callback


def wait_for_wake(detector: Model, device: int, threshold: float, scores: bool):
    frames, callback = _make_audio_queue()
    print('Listening for "Hey Jarvis". Ctrl+C to quit.', flush=True)
    highest = 0.0
    last_report = time.monotonic()
    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=FRAME_SAMPLES,
        device=device,
        channels=1,
        dtype="int16",
        callback=callback,
    ):
        while True:
            try:
                chunk = frames.get(timeout=2)
            except queue.Empty:
                continue
            predictions = detector.predict(np.frombuffer(chunk, dtype=np.int16))
            score = max(map(float, predictions.values()), default=0.0)
            highest = max(highest, score)
            now = time.monotonic()
            if scores and now - last_report >= 1.0:
                print(f"Peak wake confidence: {highest:.2f}", flush=True)
                highest = 0.0
                last_report = now
            if score >= threshold:
                print(f'\n[WAKE WORD DETECTED] Hey Jarvis ({score:.2f})', flush=True)
                return  # closes the microphone before Lewis speaks


def record_one_command(device: int, rms_threshold: float, max_seconds: float = 12.0):
    """Record until quiet, with a 6s timeout to begin speaking.

    This lightweight energy detector is for a first prototype, not a
    full speech VAD. Tune --rms for a noisy room or quiet microphone.
    """
    frames, callback = _make_audio_queue()
    start = time.monotonic()
    last_voice = None
    speech_started = False
    voice_frames = 0
    captured = []
    pre_roll = deque(maxlen=4)
    print("Speak your command now...", flush=True)
    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=FRAME_SAMPLES,
        device=device,
        channels=1,
        dtype="int16",
        callback=callback,
    ):
        while time.monotonic() - start < max_seconds:
            try:
                chunk = frames.get(timeout=0.5)
            except queue.Empty:
                continue
            samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
            rms = float(np.sqrt(np.mean(samples * samples)))
            now = time.monotonic()
            if not speech_started:
                pre_roll.append(chunk)
                if rms >= rms_threshold:
                    voice_frames += 1
                else:
                    voice_frames = 0
                if voice_frames >= 2:  # Require ~160ms of audio activity.
                    speech_started = True
                    captured.extend(pre_roll)
                    last_voice = now
                elif now - start >= 6.0:
                    print("No spoken command detected within six seconds.")
                    return None
            else:
                captured.append(chunk)
                if rms >= rms_threshold:
                    last_voice = now
                elif last_voice is not None and now - last_voice >= 1.0:
                    break

    if not speech_started:
        print("No spoken command detected.")
        return None

    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)  # 16-bit PCM
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(b"".join(captured))
    return buffer.getvalue()


def spoken_summary(reply: str) -> str | None:
    """Make an already-approved action's status audible; never grant approval."""
    if not reply:
        return None
    if reply.startswith("Approval required"):
        return "Sir, this action requires your approval in the JARVIS dashboard."
    if reply.startswith("Action update:"):
        if "Action failed:" in reply:
            return "Sir, the action failed. Please check the dashboard for details."
        return "Sir, the action finished. You can review the result in the dashboard."
    text = re.sub(r"```[\s\S]*?```", " Code block omitted. ", reply)
    text = re.sub(r"\s+", " ", text).strip()
    # Keep voice answers short, while the full response stays in JARVIS history.
    return text if text else None


def run(device: int, threshold: float, scores: bool, rms_threshold: float):
    mic = sd.query_devices(device, kind="input")
    sd.check_input_settings(
        device=device, channels=1, samplerate=SAMPLE_RATE, dtype="int16"
    )
    print(f"Windows microphone: {mic['name']} (device {device})")
    print("Loading local openWakeWord Hey Jarvis model...")
    detector = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
    api = JarvisAPI()
    print("Connected to local JARVIS voice API. No audio or token written to disk.")
    while True:
        try:
            detector.reset()
            wait_for_wake(detector, device, threshold, scores)
            try:
                api.speak("Yes, sir?")
            except Exception as err:
                print(f"Lewis greeting error: {err}")
                # Continue so an unavailable TTS worker doesn't prevent a command.
            audio = record_one_command(device, rms_threshold)
            if audio is None:
                continue
            try:
                transcript = api.transcribe(audio)
                if not transcript:
                    print("Whisper did not recognize a command.")
                    continue
                print(f"You: {transcript}")
                reply = api.ask(transcript)
                print(f"JARVIS: {reply}")

                speech = spoken_summary(reply)

                if speech:
                    # Split long answers into manageable sections.
                    chunks = textwrap.wrap(
                        speech,
                        width=850,
                        break_long_words=False,
                        break_on_hyphens=False
                    )

                    # Lewis finishes each section before continuing.
                    for chunk in chunks:
                        api.speak(chunk)

            except (requests.RequestException, RuntimeError, ValueError, OSError) as err:
                print(f"Voice request error: {err}")
            time.sleep(0.5)  # Allow speaker output to fade before rearming.
        except KeyboardInterrupt:
            print("\nHands-free JARVIS stopped.")
            return


def main():
    parser = argparse.ArgumentParser(
        description="Windows Hey Jarvis -> local Whisper -> Qwen -> Lewis"
    )
    parser.add_argument("--device", type=int, default=1,
                        help="Microphone ID (1: Brio 101; 2: JBL headset)")
    parser.add_argument("--threshold", type=float, default=0.55,
                        help="Wake-word confidence threshold (default 0.55)")
    parser.add_argument("--rms", type=float, default=350,
                        help="Command speech energy threshold (default 350)")
    parser.add_argument("--scores", action="store_true",
                        help="Print wake-word confidence while waiting")
    args = parser.parse_args()
    if not 0 < args.threshold <= 1:
        parser.error("--threshold must be between 0 and 1")
    if args.rms <= 0:
        parser.error("--rms must be positive")
    try:
        run(args.device, args.threshold, args.scores, args.rms)
    except (sd.PortAudioError, ValueError, RuntimeError, requests.RequestException) as err:
        raise SystemExit(f"Hands-free setup error: {err}") from err


if __name__ == "__main__":
    main()
