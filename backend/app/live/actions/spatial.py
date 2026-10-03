"""Route spoken/typed AKASHI commands to an open Spatial Lab scene.

Matches only while a Spatial Lab client is actively connected and the
deterministic interpreter recognises a scene instruction, so ordinary chat such
as "make it bigger" about an image is never hijacked when Spatial Lab is closed.
"""

from __future__ import annotations

from typing import List, Optional

from app.core.brain import BrainResponse
from app.core.intent import analyze_intent
from app.live.actions.base import LiveAction, LiveActionRuntime
from app.live.models import ActionMatch, LiveActionDefinition
from app.spatial.model import summarize


class SpatialSceneAction(LiveAction):
    definition = LiveActionDefinition(
        name="spatial.scene",
        description="Apply a natural-language instruction to the open Spatial Lab scene through validated scene commands.",
        input_schema={"type": "object", "properties": {"session_id": {"type": "string"}}, "additionalProperties": False},
        risk="safe",
        capabilities=("spatial", "scene", "form"),
        examples=("Make it bigger.", "Rotate it 180 degrees.", "İskeleti göster.", "Son FORM sürümünü yükle."),
    )

    def __init__(self, runtime: LiveActionRuntime) -> None:
        self.runtime = runtime

    def match(self, message: str) -> Optional[ActionMatch]:
        service = self.runtime.spatial
        if service is None:
            return None
        session = service.active_session()
        if session is None:
            return None
        if service.rules.interpret(message, summarize(session.history.state)) is None:
            return None
        return ActionMatch(score=115, arguments={"session_id": session.id}, approved=False)

    async def execute(self, message: str, session_id: str, mode: str, voice: bool, match: ActionMatch) -> BrainResponse:
        service = self.runtime.spatial
        if service is None:
            raise RuntimeError("Spatial Lab is not configured.")
        outcome = await service.interpret(match.arguments["session_id"], message, provider="chat", voice=voice)
        text = outcome.get("reply") or "Spatial Lab did not change."
        intent = analyze_intent(message)
        self.runtime.brain.record_runtime_exchange(session_id, message, text, intent, mode)  # type: ignore[arg-type]
        return BrainResponse(text=text, session_id=session_id, provider="spatial-lab", intent=intent)


def create_actions(runtime: LiveActionRuntime) -> List[LiveAction]:
    return [SpatialSceneAction(runtime)]
