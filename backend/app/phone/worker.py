"""LiveKit SIP worker for AKASHI phone calls.

Run separately from FastAPI:
    python -m app.phone.worker dev

The worker owns realtime media only. Reasoning, tools, persona, and memory remain
inside the authenticated FastAPI Core through the existing /chat pipeline.
"""

import asyncio
import json
import logging
import uuid
from typing import Any, AsyncIterable, Optional

import httpx
from livekit import rtc
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli, inference, llm, room_io
from livekit.plugins import silero

from app.core.config import Settings, get_settings


logger = logging.getLogger("akashi.phone")


class CorePhoneBridge:
    def __init__(self, settings: Settings, call_id: str, session_id: str) -> None:
        self.settings = settings
        self.call_id = call_id
        self.session_id = session_id
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=5.0))

    async def close(self) -> None:
        await self.client.aclose()

    async def event(self, state: str, **data: Any) -> None:
        payload = {"call_id": self.call_id, "state": state, **data}
        try:
            response = await self.client.post(
                f"{self.settings.phone_core_url}/phone/worker/events",
                headers={"X-Akashi-Phone-Worker-Token": self.settings.phone_worker_token or ""},
                json=payload,
            )
            response.raise_for_status()
        except (httpx.HTTPError, ValueError):
            logger.warning("Core rejected a phone lifecycle update: %s", state)

    async def answer(self, message: str) -> str:
        response = await self.client.post(
            f"{self.settings.phone_core_url}/chat",
            headers={"Authorization": f"Bearer {self.settings.api_token or ''}"},
            json={
                "message": message,
                "session_id": self.session_id,
                "mode": "private",
                "model_profile": "fast",
                "voice": True,
                "interaction_id": f"phone-{uuid.uuid4()}",
            },
        )
        response.raise_for_status()
        payload = response.json()
        text = str(payload.get("response") or "").strip()
        if not text:
            raise RuntimeError("AKASHI Core returned an empty phone response.")
        return text


class AkashiPhoneAgent(Agent):
    def __init__(self, bridge: CorePhoneBridge) -> None:
        super().__init__(
            instructions=(
                "You are the realtime telephone transport for AKASHI. "
                "The authoritative response is produced by AKASHI Core."
            ),
            llm=None,
        )
        self.bridge = bridge

    async def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool],
        model_settings: Any,
    ) -> AsyncIterable[str]:
        del tools, model_settings
        user_messages = [
            message.text_content or ""
            for message in chat_ctx.messages()
            if message.role == "user" and (message.text_content or "").strip()
        ]
        if not user_messages:
            yield "Seni dinliyorum."
            return
        try:
            yield await self.bridge.answer(user_messages[-1])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("AKASHI Core phone response failed: %s", type(exc).__name__)
            yield "Yanıt servisi şu anda erişilemiyor. Lütfen tekrar dene."


def _job_metadata(ctx: JobContext) -> dict[str, Any]:
    try:
        value = json.loads(ctx.job.metadata or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


async def entrypoint(ctx: JobContext) -> None:
    settings = get_settings()
    if not settings.phone_enabled:
        raise RuntimeError("AKASHI_PHONE_ENABLED is false.")
    required = {
        "AKASHI_API_TOKEN": settings.api_token,
        "AKASHI_PHONE_WORKER_TOKEN": settings.phone_worker_token,
        "AKASHI_PHONE_TTS_VOICE": settings.phone_tts_voice,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"Phone worker configuration is incomplete: {', '.join(missing)}")

    metadata = _job_metadata(ctx)
    call_id = str(metadata.get("call_id") or uuid.uuid4())[:128]
    direction = "outbound" if metadata.get("direction") == "outbound" else "inbound"
    room_name = ctx.room.name or f"akashi-phone-{call_id}"
    bridge = CorePhoneBridge(settings, call_id, f"phone:{call_id}")
    close_event = asyncio.Event()
    terminal_reported = False
    pending_reports: set[asyncio.Task[None]] = set()

    await bridge.event("ringing", direction=direction, room_name=room_name)
    try:
        await ctx.connect()
        participant = await ctx.wait_for_participant(kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP)
        attributes = participant.attributes
        caller_number = attributes.get("sip.phoneNumber", "unknown")
        if attributes.get("akashi.call.id"):
            call_id = attributes["akashi.call.id"][:128]
            bridge.call_id = call_id
            bridge.session_id = f"phone:{call_id}"
        callee_number: Optional[str] = metadata.get("destination") if direction == "outbound" else None
        common = {
            "direction": direction,
            "room_name": room_name,
            "caller_number": caller_number,
            "callee_number": callee_number,
        }
        await bridge.event("answered", **common)

        vad = silero.VAD.load(
            sample_rate=8000,
            min_speech_duration=0.12,
            min_silence_duration=0.35,
            prefix_padding_duration=0.25,
        )
        stt = inference.STT(
            model=settings.phone_stt_model,
            language=settings.phone_stt_language,
        )
        tts = inference.TTS(
            model=settings.phone_tts_model,
            voice=settings.phone_tts_voice,
            language=settings.phone_tts_language,
        )
        session = AgentSession(
            stt=stt,
            tts=tts,
            vad=vad,
            turn_detection="vad",
            min_endpointing_delay=0.3,
            max_endpointing_delay=1.4,
            allow_interruptions=True,
            min_interruption_duration=0.25,
            false_interruption_timeout=1.0,
            resume_false_interruption=True,
            preemptive_generation=True,
        )

        def schedule(state: str, **values: Any) -> None:
            task = asyncio.create_task(bridge.event(state, **common, **values))
            pending_reports.add(task)
            task.add_done_callback(pending_reports.discard)

        @session.on("user_state_changed")
        def on_user_state(event: Any) -> None:
            if getattr(event, "new_state", "") == "speaking":
                schedule("caller_speaking")

        @session.on("agent_state_changed")
        def on_agent_state(event: Any) -> None:
            if getattr(event, "new_state", "") == "speaking":
                schedule("assistant_speaking")

        @session.on("user_input_transcribed")
        def on_transcript(event: Any) -> None:
            transcript = str(getattr(event, "transcript", "") or "").strip()
            if transcript:
                schedule(
                    "caller_speaking",
                    transcript_role="caller",
                    transcript_text=transcript,
                    transcript_final=bool(getattr(event, "is_final", False)),
                )

        @session.on("conversation_item_added")
        def on_conversation_item(event: Any) -> None:
            item = getattr(event, "item", None)
            if isinstance(item, llm.ChatMessage) and item.role == "assistant" and item.text_content:
                schedule(
                    "assistant_speaking",
                    transcript_role="assistant",
                    transcript_text=item.text_content,
                    transcript_final=True,
                )

        @session.on("close")
        def on_close(event: Any) -> None:
            nonlocal terminal_reported
            error = getattr(event, "error", None)
            terminal_reported = True

            async def report_close() -> None:
                await bridge.event(
                    "failed" if error else "ended",
                    **common,
                    result="session_closed" if not error else None,
                    error=type(error).__name__ if error else None,
                )
                close_event.set()

            task = asyncio.create_task(report_close())
            pending_reports.add(task)
            task.add_done_callback(pending_reports.discard)

        await session.start(
            agent=AkashiPhoneAgent(bridge),
            room=ctx.room,
            room_options=room_io.RoomOptions(
                participant_identity=participant.identity,
                close_on_disconnect=True,
                delete_room_on_close=True,
            ),
        )
        await bridge.event("connected", **common)
        await session.say("AKASHI hattı açık. Seni dinliyorum.", allow_interruptions=True)
        await close_event.wait()
    except asyncio.CancelledError:
        if not terminal_reported:
            await bridge.event("ended", direction=direction, room_name=room_name, result="worker_cancelled")
        raise
    except Exception as exc:
        logger.error("Phone session failed: %s", type(exc).__name__)
        if not terminal_reported:
            await bridge.event(
                "failed",
                direction=direction,
                room_name=room_name,
                error=f"Phone worker failed: {type(exc).__name__}",
            )
        raise
    finally:
        if pending_reports:
            await asyncio.gather(*tuple(pending_reports), return_exceptions=True)
        await bridge.close()


def main() -> None:
    settings = get_settings()
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name=settings.phone_agent_name,
            ws_url=settings.livekit_url,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )
    )


if __name__ == "__main__":
    main()

