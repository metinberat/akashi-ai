"""One-shot local microphone capture and Whisper transcription for Electron.

Audio remains in memory and is discarded after transcription. The process writes
only bounded JSON lifecycle events to stdout; raw audio and credentials are never
logged or persisted.
"""

import argparse
import json
import math
import queue
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, Optional


def emit(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def probe() -> int:
    try:
        import sounddevice as sd
        import torch
        import whisper

        input_index = sd.default.device[0]
        input_device = sd.query_devices(input_index, "input")
        cache = Path.home() / ".cache" / "whisper"
        emit({
            "event": "result",
            "ok": True,
            "engine": "local-whisper",
            "cuda": bool(torch.cuda.is_available()),
            "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
            "microphone": str(input_device.get("name") or "default"),
            "models": [name for name in ("tiny", "base", "small") if (cache / f"{name}.pt").is_file()],
            "audio_persisted": False,
            "wake_word": "foundation-disabled",
        })
        return 0
    except Exception as exc:
        emit({"event": "result", "ok": False, "code": "voice_unavailable", "message": f"{type(exc).__name__}: {exc}"})
        return 2


def capture(
    sample_rate: int,
    start_timeout: float,
    max_seconds: float,
    silence_seconds: float,
    threshold_scale: float = 3.2,
    min_speech_seconds: float = 0.55,
    sustain_blocks: int = 1,
):
    import numpy as np
    import sounddevice as sd

    blocks: "queue.Queue[Any]" = queue.Queue(maxsize=200)
    preroll = deque(maxlen=max(1, int(0.45 / 0.03)))

    def callback(indata, _frames, _time_info, status) -> None:
        if status:
            return
        try:
            blocks.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass

    started = time.monotonic()
    speech_started: Optional[float] = None
    last_voice: Optional[float] = None
    audio = []
    calibration = []
    sustained = 0
    with sd.InputStream(samplerate=sample_rate, channels=1, dtype="float32", blocksize=480, callback=callback):
        emit({"event": "state", "state": "listening"})
        while True:
            now = time.monotonic()
            if speech_started is None and now - started >= start_timeout:
                raise TimeoutError("No speech was detected before the listening timeout.")
            if speech_started is not None and now - speech_started >= max_seconds:
                break
            try:
                block = blocks.get(timeout=0.5)
            except queue.Empty:
                continue
            rms = math.sqrt(float(np.mean(np.square(block))) + 1e-12)
            if now - started < 0.5:
                calibration.append(rms)
            noise = sum(calibration) / len(calibration) if calibration else 0.002
            threshold = max(0.008, noise * threshold_scale)
            if speech_started is None:
                preroll.append(block)
                if rms >= threshold:
                    sustained += 1
                else:
                    sustained = 0
                if sustained >= sustain_blocks:
                    speech_started = now
                    last_voice = now
                    emit({"event": "state", "state": "speech_started", "detected_at_ms": int(time.time() * 1000)})
                    audio.extend(preroll)
                    preroll.clear()
            else:
                audio.append(block)
                if rms >= threshold:
                    last_voice = now
                if last_voice is not None and now - last_voice >= silence_seconds and now - speech_started >= min_speech_seconds:
                    break
    if not audio:
        raise TimeoutError("No speech was detected.")
    return np.concatenate(audio).astype("float32")


def transcribe(model_name: str, language: str, barge_in: bool = False) -> int:
    try:
        import torch
        import whisper

        # Barge-in mode (mic armed while AKASHI's own TTS is playing) uses a higher VAD
        # threshold, a longer minimum speech duration, and requires the signal to sustain
        # across multiple blocks before counting as speech, to cut short spurious triggers
        # from speaker bleed before they even reach transcription/echo-comparison.
        audio = capture(
            16_000, 12.0, 25.0, 0.9,
            threshold_scale=4.5 if barge_in else 3.2,
            min_speech_seconds=0.7 if barge_in else 0.55,
            sustain_blocks=2 if barge_in else 1,
        )
        emit({"event": "state", "state": "transcribing"})
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = whisper.load_model(model_name, device=device, download_root=str(Path.home() / ".cache" / "whisper"))
        result = model.transcribe(
            audio,
            language=None if language == "auto" else language,
            fp16=device == "cuda",
            temperature=0,
            condition_on_previous_text=False,
        )
        text = str(result.get("text") or "").strip()
        if not text:
            raise TimeoutError("Speech was detected but no transcript was produced.")
        emit({
            "event": "result",
            "ok": True,
            "transcript": text[:4_000],
            "language": str(result.get("language") or language),
            "engine": "local-whisper",
            "device": device,
        })
        return 0
    except TimeoutError as exc:
        emit({"event": "result", "ok": False, "code": "no_speech", "message": str(exc)})
        return 3
    except Exception as exc:
        emit({"event": "result", "ok": False, "code": "recognition_error", "message": f"{type(exc).__name__}: {exc}"})
        return 4


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--language", choices=("auto", "tr", "en"), default="auto")
    parser.add_argument("--model", choices=("tiny", "base", "small"), default="base")
    parser.add_argument("--barge-in", action="store_true")
    args = parser.parse_args()
    return probe() if args.probe else transcribe(args.model, args.language, barge_in=args.barge_in)


if __name__ == "__main__":
    sys.exit(main())
