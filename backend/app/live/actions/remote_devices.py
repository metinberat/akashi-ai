"""Answer "which connected device can provide X?" from live remote sessions.

Read-only: it reports the capability registry; it never activates a sensor.
"""

from __future__ import annotations

import re
from typing import List, Optional

from app.core.brain import BrainResponse
from app.core.intent import analyze_intent
from app.live.actions.base import LiveAction, LiveActionRuntime, is_turkish, normalize_text
from app.live.models import ActionMatch, LiveActionDefinition

DEVICE_WORDS = re.compile(r"\b(device|devices|phone|iphone|ipad|mac|laptop|tablet|cihaz|cihazlar|cihazlari|telefon|telefonum)\b")
QUESTION_WORDS = re.compile(r"\b(which|what|connected|online|available|can provide|hangi|hangisi|bagli|cevrimici|saglayabilir|var mi)\b")
CAPABILITY_WORDS = {
    "camera": r"\b(camera|kamera)\b", "microphone": r"\b(microphone|mic|mikrofon)\b", "touch": r"\b(touch|dokunma|dokunmatik)\b",
    "display": r"\b(display|screen|ekran)\b", "hand_tracking": r"\b(hand tracking|el takibi)\b", "keyboard": r"\b(keyboard|klavye)\b",
    "voice_input": r"\b(voice input|speech recognition|ses tanima)\b", "approval_surface": r"\b(approval|onay)\b",
    "orientation": r"\b(orientation|gyro|motion|jiroskop|hareket sensoru)\b", "notifications": r"\b(notification|bildirim)\b",
}


class RemoteDevicesAction(LiveAction):
    definition = LiveActionDefinition(
        name="remote.devices",
        description="Report which remote devices are connected and which can provide a capability (camera, microphone, touch, display...).",
        input_schema={"type": "object", "properties": {"capability": {"type": "string"}}, "additionalProperties": False},
        risk="safe",
        capabilities=("devices", "remote", "capabilities"),
        examples=("Which device can provide a camera?", "Which devices are connected?", "Hangi cihaz mikrofon sağlayabilir?"),
    )

    def __init__(self, runtime: LiveActionRuntime) -> None:
        self.runtime = runtime

    def match(self, message: str) -> Optional[ActionMatch]:
        if self.runtime.remote is None:
            return None
        text = normalize_text(message)
        if not DEVICE_WORDS.search(text) or not QUESTION_WORDS.search(text):
            return None
        capability = next((name for name, pattern in CAPABILITY_WORDS.items() if re.search(pattern, text)), None)
        return ActionMatch(score=80, arguments={"capability": capability} if capability else {})

    async def execute(self, message: str, session_id: str, mode: str, voice: bool, match: ActionMatch) -> BrainResponse:
        registry = self.runtime.remote.hub.registry  # type: ignore[union-attr]
        text = registry.describe(match.arguments.get("capability"), "tr" if is_turkish(message) else "en")
        intent = analyze_intent(message)
        self.runtime.brain.record_runtime_exchange(session_id, message, text, intent, mode)  # type: ignore[arg-type]
        return BrainResponse(text=text, session_id=session_id, provider="remote-presence", intent=intent)


def create_actions(runtime: LiveActionRuntime) -> List[LiveAction]:
    return [RemoteDevicesAction(runtime)]
