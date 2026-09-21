from typing import Any, Dict, List, Optional

from app.core.brain import BrainResponse
from app.live.actions.base import LiveAction, LiveActionRuntime, is_turkish, normalize_text
from app.live.models import ActionMatch, LiveActionDefinition


class OneShotVisionAction(LiveAction):
    capture_action = ""
    source_name = ""

    def __init__(self, runtime: LiveActionRuntime) -> None:
        self.runtime = runtime

    async def execute(
        self,
        message: str,
        session_id: str,
        mode: str,
        voice: bool,
        match: ActionMatch,
    ) -> BrainResponse:
        capture = await self.runtime.desktop.execute(
            self.capture_action, match.arguments, match.approved
        )
        data: Dict[str, Any] = capture.get("data", {})
        encoded = data.get("base64") if isinstance(data, dict) else None
        media_type = data.get("media_type") if isinstance(data, dict) else None
        if (
            not isinstance(encoded, str)
            or not encoded
            or len(encoded) > 2_000_000
            or media_type != "image/jpeg"
        ):
            raise RuntimeError("Visual capture returned an invalid image.")
        provider = self.runtime.model_router.provider_for("vision")
        context = (
            f"A one-shot {self.source_name} image was captured for this interaction. "
            "It is current runtime evidence, not a continuous feed. Describe only "
            "what is visibly supported. Do not confuse screen content with the physical room. "
            + (
                "The user's latest message is Turkish; reply only in Turkish."
                if is_turkish(message)
                else "Reply only in the language of the user's latest message."
            )
        )
        return await self.runtime.brain.respond(
            message=message,
            session_id=session_id,
            mode=mode,  # type: ignore[arg-type]
            provider=provider,
            voice=voice,
            images=[f"data:image/jpeg;base64,{encoded}"],
            profile="vision",
            runtime_context=context,
        )


class ScreenVisionAction(OneShotVisionAction):
    capture_action = "take_screenshot"
    source_name = "Windows desktop screenshot"
    definition = LiveActionDefinition(
        name="vision.screen",
        description="Capture one explicit desktop screenshot and analyze it with a vision model.",
        input_schema={"type": "object", "additionalProperties": False},
        risk="safe",
        capabilities=("screen", "vision", "desktop"),
        examples=("Ekranıma bak.", "Look at my screen and tell me what you see."),
    )

    def match(self, message: str) -> Optional[ActionMatch]:
        text = normalize_text(message)
        source = any(word in text for word in ("ekran", "screen", "desktop", "screenshot"))
        inspect = any(word in text for word in ("bak", "goru", "gordugunu", "incele", "look", "see", "analyze", "inspect"))
        return ActionMatch(score=120, arguments={}, approved=True) if source and inspect else None


class CameraVisionAction(OneShotVisionAction):
    capture_action = "capture_camera_frame"
    source_name = "physical webcam frame"
    definition = LiveActionDefinition(
        name="vision.camera",
        description="Capture one explicit webcam frame, release the camera, and analyze it.",
        input_schema={"type": "object", "additionalProperties": False},
        risk="safe",
        capabilities=("camera", "vision", "desktop"),
        examples=("Kameradan bak.", "Look through the webcam."),
    )

    def match(self, message: str) -> Optional[ActionMatch]:
        text = normalize_text(message)
        source = any(word in text for word in ("kamera", "kameradan", "webcam", "camera"))
        inspect = any(word in text for word in ("bak", "goru", "gordugunu", "incele", "look", "see", "analyze", "inspect"))
        return ActionMatch(score=125, arguments={}, approved=True) if source and inspect else None


def create_actions(runtime: LiveActionRuntime) -> List[LiveAction]:
    return [ScreenVisionAction(runtime), CameraVisionAction(runtime)]
