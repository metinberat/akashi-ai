"""Remote voice: a device's speech reaches AKASHI through the existing paths.

The device turns speech into text on the device (native or browser speech
recognition; the engine is reported and recorded) and sends a transcript.
Audio never travels to Core in this version.

    transcript ─┬─ voice.spatial (+ subscribed scene) → Spatial Lab interpreter → shared command path
                └─ assistant.chat (owner-granted)    → AKASHI chat pipeline with live actions limited
                                                       to REMOTE_LIVE_ACTIONS (no computer control)

Lifecycle reuses ``VoiceSessionManager`` (privacy-safe metadata only), so the
desktop HUD can show that a remote voice turn is thinking/speaking. The reply
text is returned to the device, which speaks it with on-device synthesis.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional

from app.remote import context as remote_context
from app.remote.hub import MessageContext, RemoteError, RemoteHub
from app.remote.sessions import RemoteSession

VOICE_STATES = {"listening", "transcribing", "speaking", "idle", "error", "interrupted"}


class RemoteVoice:
    def __init__(self, hub: RemoteHub, spatial: Any, chat: Optional[Callable[..., Awaitable[Any]]], voice_sessions: Any) -> None:
        self.hub = hub
        self.spatial = spatial
        self.chat = chat
        self.voice_sessions = voice_sessions
        hub.register("voice.utterance", self._utterance, any_of=("voice.spatial", "assistant.chat"), rate_class="voice")
        hub.register("voice.state", self._state, delivery="realtime", any_of=("voice.spatial", "assistant.chat"))
        hub.on("closed", self._closed)

    def _voice_session(self, session: RemoteSession, language: str) -> Optional[str]:
        if self.voice_sessions is None:
            return None
        voice_id = session.data.get("voice")
        if voice_id and self.voice_sessions.get(voice_id):
            return voice_id
        item = self.voice_sessions.start(f"remote:{session.id}", language)
        session.data["voice"] = item["id"]
        return item["id"]

    def _transition(self, voice_id: Optional[str], *states: str, **values: Any) -> None:
        if not voice_id:
            return
        for state in states:
            try:
                self.voice_sessions.transition(voice_id, state, **values)
            except (KeyError, ValueError):
                continue

    async def _utterance(self, ctx: MessageContext) -> Dict[str, Any]:
        body = ctx.envelope.body
        text = body.get("text")
        if not isinstance(text, str) or not 0 < len(text.strip()) <= 500:
            raise RemoteError("bad_request", "text must be 1-500 characters.")
        language = body.get("language") if body.get("language") in {"auto", "tr", "en"} else "auto"
        engine = str(body.get("engine") or "unknown")[:40]
        session = ctx.session
        voice_id = self._voice_session(session, language)
        self._transition(voice_id, "transcribing", "thinking", last_user_utterance=text[:500])
        spatial_id = session.data.get("spatial")
        outcome: Dict[str, Any] = {"route": "none", "understood": False, "engine": engine, "voice_session": voice_id}
        if "voice.spatial" in session.scopes and spatial_id and f"spatial:{spatial_id}" in session.channels:
            spatial_reply = await self.spatial.interpret(ctx, spatial_id, text.strip(), "voice")
            outcome["spatial"] = spatial_reply
            if spatial_reply.get("understood"):
                outcome.update(route="spatial", understood=True, reply=spatial_reply.get("reply"))
        if not outcome["understood"] and "assistant.chat" in session.scopes and self.chat is not None:
            token = remote_context.enter({"scopes": session.scopes, "provenance": ctx.provenance("voice"), "spatial": spatial_id})
            try:
                response = await self.chat(message=text.strip(), session_id=f"remote-{session.device.get('id')}"[:128],
                                           mode="private", voice=True)
            finally:
                remote_context.leave(token)
            outcome.update(route="assistant", understood=True, reply=response.text, provider=response.provider)
        if not outcome.get("reply"):
            base = (outcome.get("spatial") or {}).get("reply") or ("Bunu anlayamadım." if language == "tr" else "I couldn't act on that.")
            outcome["reply"] = base + (
                "" if "assistant.chat" in session.scopes else (" Bu cihaz yalnızca sahne komutları verebilir." if language == "tr"
                                                               else " This device may only give scene instructions."))
        self._transition(voice_id, "acting" if outcome["understood"] else "speaking", "speaking",
                         last_assistant_utterance=str(outcome["reply"])[:500])
        return outcome

    async def _state(self, ctx: MessageContext) -> Optional[Dict[str, Any]]:
        state = ctx.envelope.body.get("state")
        if state not in VOICE_STATES:
            raise RemoteError("bad_request", "Unknown voice state.")
        voice_id = self._voice_session(ctx.session, "auto")
        self._transition(voice_id, state)
        return None

    def _closed(self, session: RemoteSession) -> None:
        voice_id = session.data.get("voice")
        if voice_id and self.voice_sessions is not None:
            try:
                self.voice_sessions.stop(voice_id)
            except KeyError:
                pass
