"""AKASHI fast voice path: a persistent Gemini Live Native Audio session.

WHY THIS EXISTS
    The one-shot flow in `listen.py` (record until silence -> local Whisper ->
    POST /chat -> browser TTS) is a request/response pipeline: several serial
    stages before a reply can even start forming. A native-audio Gemini Live
    session collapses that into one continuous, bidirectional audio stream -
    the model listens and speaks in the same turn, which is what makes casual
    conversation feel close to instant.

    Tool use, research, memory and every other AKASHI Core capability are
    deliberately NOT reimplemented here. This process has exactly one tool,
    `consult_akashi_core`, which forwards the user's request to the existing
    FastAPI /chat endpoint - the same Core, memory, research and persona the
    rest of the app already uses. This script's only job is to be a fast,
    stable mouth and ear in front of it.

PROTOCOL (stdin/stdout, both newline-delimited JSON)
    First line on stdin is the handshake:
        {"gemini_api_key": "...", "core_base_url": "http://127.0.0.1:8000",
         "core_token": "...", "voice_name": "Charon", "language": "auto",
         "session_id": "...", "identity": "...", "voice_style": "..."}
    session_id is optional: when the host supplies the conversation id the user
    is already typing in, a voice turn that consults Core continues that same
    conversation instead of opening a private one that nothing else can see.
    Further stdin lines are control commands:
        {"cmd": "interrupt"}   - stop AKASHI mid-sentence, open the mic now
        {"cmd": "text", "text": "..."}   - inject a typed message as a turn
        {"cmd": "stop"}        - shut down cleanly
    Stdout emits one JSON object per line:
        {"event": "state", "state": "connecting|listening|thinking|speaking|interrupted|error"}
        {"event": "transcript", "role": "user|assistant", "text": "...", "final": true}
        {"event": "tool", "name": "consult_akashi_core", "status": "start|done|error", "detail": "..."}
        {"event": "latency", "label": "first_audio_byte", "ms": 812}
        {"event": "error", "message": "..."}
        {"event": "ready"}
    Raw audio never touches stdout/stdin; it stays inside sounddevice <-> Gemini.
"""
from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
import traceback
import uuid
from typing import Any, Optional

import numpy as np
import sounddevice as sd

LIVE_MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025"
CHANNELS = 1
SEND_SAMPLE_RATE = 16_000
RECEIVE_SAMPLE_RATE = 24_000
CHUNK_SIZE = 1024

# Endpointing / turn-taking. Silence-first: this is most of the perceived delay
# before a reply starts, not model latency, so it is the first thing worth
# tuning if a reply feels slow to start.
SILENCE_DURATION_MS = 700
PREFIX_PADDING_MS = 250

# Echo tail: how long after AKASHI stops speaking the microphone stays under
# EchoGuard's suspicion rather than fully open. Replaced with the real
# output-device latency once the playback stream reports it.
_TAIL_MARGIN = 0.12
_DEFAULT_OUT_LATENCY = 0.20

TOOL_DECLARATIONS = [
    {
        "name": "consult_akashi_core",
        "description": (
            "Use this for ANYTHING beyond casual conversation: web research, opening "
            "apps or files, system or device actions, scheduling, memory lookups or "
            "saves, task execution, vision/screen analysis, image generation, or any "
            "question needing a tool or real-time information you do not already have. "
            "Send the user's request in their own words, with enough context to act on "
            "it standalone. You have no tools of your own - do not attempt these "
            "yourself or guess a result. After it returns, speak the answer it gives "
            "you; do not add unverified detail on top of it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "request": {
                    "type": "STRING",
                    "description": "The user's request, in their own words, standalone (no 'it'/'that' referring to unheard context).",
                },
            },
            "required": ["request"],
        },
    },
]


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def emit_state(state: str) -> None:
    emit({"event": "state", "state": state})


_CTRL_RE_CHARS = "".join(chr(c) for c in range(0, 9)) + "".join(chr(c) for c in range(11, 32))
_CTRL_TABLE = str.maketrans("", "", _CTRL_RE_CHARS)


def clean_transcript(text: str) -> str:
    return text.translate(_CTRL_TABLE).strip()


class EchoGuard:
    """Tells the user's voice apart from AKASHI's own voice coming back through
    the speakers, so the microphone can stay open through the echo tail instead
    of being blanket-muted. Ported from the Mark 54 voice stack (core/echo.py):
    band-energy spectral subtraction plus a self-calibrating echo-gain estimate,
    both sample-rate agnostic (mic runs at 16 kHz, playback at 24 kHz).
    """

    _BAND_EDGES = (200, 400, 700, 1100, 1700, 2600, 3800, 5200, 7000)
    _HISTORY_S = 1.5
    _MIN_LEVEL = 0.06
    _MIN_USER = 0.15
    _HEAD_Q = 97
    _HEAD_MULT = 1.15
    _UNRELIABLE_FLOOR = 0.22
    _BLOCKS_NORMAL = 5
    _BLOCKS_NOISY = 12
    _FLOOR_WINDOW = 60
    _FLOOR_Q = 35
    _WARMUP = 16
    _RELEARN_RUN = 28

    def __init__(self) -> None:
        self._hist: list[tuple[float, np.ndarray, float]] = []
        self._residuals: list[float] = []
        self._floor = 0.10
        self._head = 0.13
        self._run = 0

    @staticmethod
    def band_energies(pcm, sr: int) -> np.ndarray:
        x = np.asarray(pcm, dtype=np.float32)
        if x.size < 64:
            return np.zeros(len(EchoGuard._BAND_EDGES) - 1, dtype=np.float32)
        x = x - x.mean()
        n = 1 << (int(x.size) - 1).bit_length()
        mag = np.abs(np.fft.rfft(x * np.hanning(x.size), n=n))
        freqs = np.fft.rfftfreq(n, 1.0 / sr)
        out = np.empty(len(EchoGuard._BAND_EDGES) - 1, dtype=np.float32)
        for i in range(len(EchoGuard._BAND_EDGES) - 1):
            m = (freqs >= EchoGuard._BAND_EDGES[i]) & (freqs < EchoGuard._BAND_EDGES[i + 1])
            out[i] = float(mag[m].sum())
        return out

    def reset(self) -> None:
        self._hist.clear()

    def note_output(self, pcm, sr: int, level: float, when: Optional[float] = None) -> None:
        try:
            t = time.monotonic() if when is None else when
            self._hist.append((t, self.band_energies(pcm, sr), float(level)))
            cutoff = t - self._HISTORY_S
            if len(self._hist) > 8:
                self._hist = [h for h in self._hist if h[0] >= cutoff]
        except Exception:
            pass

    def is_user_speech(self, pcm, sr: int, level: float, when: Optional[float] = None) -> bool:
        try:
            if level < self._MIN_LEVEL:
                self._run = 0
                return False
            if not self._hist:
                return True

            t = time.monotonic() if when is None else when
            bands = self.band_energies(pcm, sr)
            total = float(bands.sum())
            if total <= 1e-9:
                return False

            best_res, best_level = 1.0, 0.0
            for ts, ref, ref_level in self._hist:
                if ts > t or t - ts > self._HISTORY_S:
                    continue
                denom = float(np.dot(ref, ref))
                if denom < 1e-12:
                    continue
                alpha = max(0.0, float(np.dot(bands, ref)) / denom)
                residual = np.maximum(bands - alpha * ref, 0.0)
                ratio = float(residual.sum()) / total
                if ratio < best_res:
                    best_res, best_level = ratio, ref_level

            if best_level <= 0.0:
                return True

            warming = len(self._residuals) < self._WARMUP
            thr = max(self._MIN_USER, self._head * self._HEAD_MULT)
            speech = (not warming) and best_res >= thr

            if speech:
                self._run += 1
                if self._run > self._RELEARN_RUN:
                    self._residuals.clear()
                    self._run = 0
                    return False
                return True

            self._run = 0
            self._residuals.append(best_res)
            if len(self._residuals) > self._FLOOR_WINDOW:
                del self._residuals[: -self._FLOOR_WINDOW]
            if len(self._residuals) >= self._WARMUP:
                self._floor = float(np.percentile(self._residuals, self._FLOOR_Q))
                self._head = float(np.percentile(self._residuals, self._HEAD_Q))
            return False
        except Exception:
            return False


class _ReconnectSignal(Exception):
    """Raised to force a clean, voluntary session rebuild (not an error)."""


class AkashiLiveVoice:
    def __init__(self, handshake: dict) -> None:
        self.api_key: str = handshake["gemini_api_key"]
        self.core_base_url: str = handshake.get("core_base_url", "").rstrip("/")
        self.core_token: str = handshake.get("core_token", "")
        self.voice_name: str = handshake.get("voice_name") or "Charon"
        self.language: str = handshake.get("language") or "auto"
        self.identity: str = handshake.get("identity") or "You are AKASHI, a composed and precise AI assistant."
        self.voice_style: str = handshake.get("voice_style") or "Keep voice replies brief and speakable."
        requested_session = str(handshake.get("session_id") or "").strip()
        self.session_id = requested_session or f"voice-live-{uuid.uuid4().hex[:12]}"

        self.session = None
        self.audio_in_queue: Optional[asyncio.Queue] = None
        self.out_queue: Optional[asyncio.Queue] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._is_speaking = False
        self._speaking_lock = threading.Lock()
        self._echo = EchoGuard()
        self._out_latency = _DEFAULT_OUT_LATENCY
        self._tail_until = 0.0
        self._turn_done_event: Optional[asyncio.Event] = None
        self._interrupted = False
        self._resume_handle: Optional[str] = None
        self._stop_requested = False
        self._speech_start_ms: Optional[int] = None  # for first-audio-byte latency
        self._first_audio_reported = True

    # ── stdin control channel ───────────────────────────────────────────────

    def _handle_command(self, cmd: dict) -> None:
        kind = cmd.get("cmd")
        if kind == "interrupt":
            self.interrupt()
        elif kind == "stop":
            self._stop_requested = True
        elif kind == "text" and self._loop and self.session:
            text = str(cmd.get("text") or "").strip()
            if text:
                asyncio.run_coroutine_threadsafe(
                    self.session.send_client_content(
                        turns={"role": "user", "parts": [{"text": text}]},
                        turn_complete=True,
                    ),
                    self._loop,
                )

    def _stdin_reader(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                cmd = json.loads(line)
            except Exception:
                continue
            if self._loop:
                self._loop.call_soon_threadsafe(self._handle_command, cmd)

    # ── barge-in ─────────────────────────────────────────────────────────────

    def interrupt(self) -> None:
        self._interrupted = True
        q = self.audio_in_queue
        if q:
            while True:
                try:
                    q.get_nowait()
                except Exception:
                    break
        self.set_speaking(False)
        if self._turn_done_event:
            self._turn_done_event.clear()
        emit({"event": "state", "state": "interrupted"})

    def set_speaking(self, value: bool) -> None:
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self._tail_until = 0.0
            emit_state("speaking")
        else:
            self._tail_until = time.monotonic() + self._out_latency + _TAIL_MARGIN
            emit_state("listening")

    def _tail_active(self) -> bool:
        return time.monotonic() < self._tail_until

    # ── Gemini Live config ──────────────────────────────────────────────────

    def _build_config(self):
        from google.genai import types as gtypes

        lang_note = ""
        if self.language != "auto":
            lang_note = (
                f"\n\nLANGUAGE: Speak and understand primarily in "
                f"{'Turkish' if self.language == 'tr' else 'English'} unless the user "
                f"clearly switches language."
            )
        system_instruction = (
            f"{self.identity}\n\n{self.voice_style}{lang_note}\n\n"
            "You are the fast conversational voice of AKASHI. For plain conversation, "
            "answer directly and briefly yourself. For anything requiring a tool, "
            "real-world action, research, memory, or information you don't already "
            "have, call consult_akashi_core - never guess or fabricate a result."
        )

        detect = gtypes.AutomaticActivityDetection(
            silence_duration_ms=SILENCE_DURATION_MS,
            prefix_padding_ms=PREFIX_PADDING_MS,
        )

        return gtypes.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction=system_instruction,
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            session_resumption=gtypes.SessionResumptionConfig(handle=self._resume_handle),
            context_window_compression=gtypes.ContextWindowCompressionConfig(
                sliding_window=gtypes.SlidingWindow(),
            ),
            realtime_input_config=gtypes.RealtimeInputConfig(automatic_activity_detection=detect),
            speech_config=gtypes.SpeechConfig(
                voice_config=gtypes.VoiceConfig(
                    prebuilt_voice_config=gtypes.PrebuiltVoiceConfig(voice_name=self.voice_name)
                )
            ),
        )

    # ── the one tool: hand off to AKASHI Core ───────────────────────────────

    async def _consult_core(self, request_text: str) -> str:
        import httpx

        if not self.core_base_url:
            return "AKASHI Core is not configured on this device."

        emit({"event": "tool", "name": "consult_akashi_core", "status": "start", "detail": request_text[:200]})
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.core_base_url}/chat",
                    headers={"Authorization": f"Bearer {self.core_token}"} if self.core_token else {},
                    json={
                        "message": request_text,
                        "session_id": self.session_id,
                        "mode": "private",
                        "model_profile": "quality",
                        "voice": True,
                    },
                )
                response.raise_for_status()
                data = response.json()
                text = str(data.get("response") or "").strip()
                elapsed_ms = int((time.monotonic() - started) * 1000)
                emit({"event": "tool", "name": "consult_akashi_core", "status": "done", "detail": f"{elapsed_ms}ms"})
                return text or "AKASHI Core returned an empty response."
        except Exception as exc:
            emit({"event": "tool", "name": "consult_akashi_core", "status": "error", "detail": str(exc)[:200]})
            return "AKASHI Core could not complete that request right now."

    async def _execute_tool(self, fc) -> Any:
        from google.genai import types as gtypes

        name = fc.name
        args = dict(fc.args or {})
        if name == "consult_akashi_core":
            emit_state("thinking")
            result = await self._consult_core(str(args.get("request") or ""))
        else:
            result = f"Unknown tool: {name}"
        return gtypes.FunctionResponse(id=fc.id, name=name, response={"result": result})

    # ── audio in/out tasks ───────────────────────────────────────────────────

    async def _send_realtime(self) -> None:
        from google.genai import types as gtypes

        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(
                audio=gtypes.Blob(data=msg["data"], mime_type=msg.get("mime_type", "audio/pcm"))
            )

    def _pcm_level(self, samples) -> float:
        if samples.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(samples.astype(np.float32) / 32768.0))))

    async def _listen_audio(self) -> None:
        loop = asyncio.get_event_loop()

        def callback(indata, _frames, _time_info, status) -> None:
            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking:
                return  # nothing streamed while AKASHI talks
            if self._tail_active():
                try:
                    level = self._pcm_level(indata[:, 0]) if indata.ndim > 1 else self._pcm_level(indata)
                    if not self._echo.is_user_speech(indata, SEND_SAMPLE_RATE, level):
                        return
                    self._tail_until = 0.0
                except Exception:
                    return
            data = indata.tobytes()
            loop.call_soon_threadsafe(self.out_queue.put_nowait, {"data": data, "mime_type": "audio/pcm"})

        with sd.InputStream(
            samplerate=SEND_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
            callback=callback,
        ):
            while not self._stop_requested:
                await asyncio.sleep(0.1)
        raise _ReconnectSignal("stop requested")

    async def _receive_audio(self) -> None:
        out_buf: list[str] = []
        in_buf: list[str] = []

        while True:
            async for response in self.session.receive():
                sru = getattr(response, "session_resumption_update", None)
                if sru is not None and getattr(sru, "resumable", False) and getattr(sru, "new_handle", None):
                    self._resume_handle = sru.new_handle

                if response.data:
                    if not self._interrupted:
                        if self._turn_done_event and self._turn_done_event.is_set():
                            self._turn_done_event.clear()
                        if not self._first_audio_reported and self._speech_start_ms is not None:
                            self._first_audio_reported = True
                            elapsed = int(time.time() * 1000) - self._speech_start_ms
                            emit({"event": "latency", "label": "first_audio_byte", "ms": elapsed})
                        self.audio_in_queue.put_nowait(response.data)

                if response.server_content:
                    sc = response.server_content
                    if sc.output_transcription and sc.output_transcription.text:
                        txt = clean_transcript(sc.output_transcription.text)
                        if txt:
                            out_buf.append(txt)
                    if sc.input_transcription and sc.input_transcription.text:
                        txt = clean_transcript(sc.input_transcription.text)
                        if txt:
                            in_buf.append(txt)
                            if self._speech_start_ms is None or self._first_audio_reported:
                                self._speech_start_ms = int(time.time() * 1000)
                                self._first_audio_reported = False
                    if sc.turn_complete:
                        if self._turn_done_event:
                            self._turn_done_event.set()
                        if self._interrupted:
                            self._interrupted = False
                            in_buf, out_buf = [], []
                            continue
                        full_in = " ".join(in_buf).strip()
                        if full_in:
                            emit({"event": "transcript", "role": "user", "text": full_in, "final": True})
                        in_buf = []
                        full_out = " ".join(out_buf).strip()
                        if full_out:
                            emit({"event": "transcript", "role": "assistant", "text": full_out, "final": True})
                        out_buf = []
                        self._speech_start_ms = None
                        self._first_audio_reported = True

                if response.tool_call:
                    fn_responses = [await self._execute_tool(fc) for fc in response.tool_call.function_calls]
                    await self.session.send_tool_response(function_responses=fn_responses)

    async def _play_audio(self) -> None:
        stream = sd.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE, channels=CHANNELS, dtype="int16", blocksize=CHUNK_SIZE,
        )
        stream.start()
        try:
            lat = float(getattr(stream, "latency", 0.0) or 0.0)
            if 0.0 < lat < 1.0:
                self._out_latency = lat
        except Exception:
            pass

        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(self.audio_in_queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    if self._turn_done_event and self._turn_done_event.is_set() and self.audio_in_queue.empty():
                        self.set_speaking(False)
                        self._turn_done_event.clear()
                    continue
                self.set_speaking(True)
                batch = bytearray(chunk)
                while len(batch) < 9600:
                    try:
                        batch.extend(self.audio_in_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                try:
                    pcm = np.frombuffer(bytes(batch), dtype=np.int16)
                    lvl = self._pcm_level(pcm)
                    self._echo.note_output(pcm, RECEIVE_SAMPLE_RATE, lvl)
                except Exception:
                    pass
                await asyncio.to_thread(stream.write, bytes(batch))
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    # ── main loop: connect, run, recover ────────────────────────────────────

    async def run(self) -> None:
        from google import genai

        self._loop = asyncio.get_event_loop()
        threading.Thread(target=self._stdin_reader, daemon=True).start()

        backoff = 3
        while not self._stop_requested:
            resumed_with = self._resume_handle is not None
            voluntary_reconnect = False
            fatal_error = False
            try:
                emit_state("connecting")
                config = self._build_config()
                client = genai.Client(api_key=self.api_key, http_options={"api_version": "v1beta"})

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session = session
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue = asyncio.Queue(maxsize=100)
                    self._turn_done_event = asyncio.Event()
                    self._interrupted = False
                    backoff = 3

                    emit({"event": "ready"})
                    if resumed_with:
                        emit({"event": "state", "state": "listening", "resumed": True})
                    else:
                        emit_state("listening")

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())

            except* _ReconnectSignal:
                voluntary_reconnect = True
            except* Exception as eg:
                for exc in eg.exceptions:
                    err_str = str(exc)
                    print(f"[AKASHI Voice] Error ({type(exc).__name__}): {exc}", file=sys.stderr)
                    traceback.print_exception(exc)

                    if resumed_with and (
                        "resum" in err_str.lower() or "handle" in err_str.lower()
                        or "INVALID_ARGUMENT" in err_str or "NOT_FOUND" in err_str
                    ):
                        self._resume_handle = None
                        backoff = 1
                        continue

                    if "API key not valid" in err_str or "1007" in err_str:
                        emit({"event": "error", "message": "invalid_api_key"})
                        fatal_error = True
                        continue

                    is_net_err = any(k in err_str for k in (
                        "TimeoutError", "timed out", "getaddrinfo", "CancelledError",
                        "ConnectionRefusedError", "OSError", "Cannot connect",
                    ))
                    backoff = min(backoff * 2, 60) if is_net_err else 3
                    emit({"event": "error", "message": err_str[:300], "transient": True})
            finally:
                self.session = None

            if fatal_error:
                return
            if self._stop_requested:
                break
            if voluntary_reconnect:
                continue
            self.set_speaking(False)
            emit_state("connecting")
            await asyncio.sleep(backoff)

        emit_state("idle")


def main() -> int:
    first_line = sys.stdin.readline()
    try:
        handshake = json.loads(first_line)
    except Exception:
        emit({"event": "error", "message": "invalid_handshake"})
        return 1
    if not handshake.get("gemini_api_key"):
        emit({"event": "error", "message": "missing_api_key"})
        return 1

    voice = AkashiLiveVoice(handshake)
    try:
        asyncio.run(voice.run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
