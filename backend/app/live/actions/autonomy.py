import re
from typing import List, Optional

from app.core.brain import BrainResponse
from app.core.intent import analyze_intent
from app.live.actions.base import LiveAction, LiveActionRuntime, is_turkish, normalize_text
from app.live.models import ActionMatch, LiveActionDefinition


LONG_GOAL_MARKERS = (
    "bastan sona", "baştan sona", "tamamini tamamla", "tamamını tamamla",
    "bitirene kadar", "sonuca kadar", "entire objective", "from beginning to end",
    "complete the whole", "finish the entire", "inspect the references",
)
WORKFLOW_VERBS = (
    "incele", "arastir", "araştır", "duzenle", "düzenle", "render", "export", "aktar",
    "inspect", "research", "modify", "build", "test", "verify", "place", "open", "create",
)


class AutonomyGoalAction(LiveAction):
    definition = LiveActionDefinition(
        name="autonomy.goal",
        description="Create a durable long-horizon goal graph and execute verified subgoals across applications.",
        input_schema={
            "type": "object",
            "properties": {"goal": {"type": "string", "maxLength": 8000}},
            "required": ["goal"], "additionalProperties": False,
        },
        risk="confirm",
        capabilities=("planning", "recovery", "browser", "desktop", "files", "vision", "skills"),
        examples=("Referansları incele, Blender'da düzenle, render al, doğrula ve projeye yerleştir.",),
    )

    def __init__(self, runtime: LiveActionRuntime) -> None:
        self.runtime = runtime

    def match(self, message: str) -> Optional[ActionMatch]:
        text = normalize_text(message)
        explicit = any(marker in text for marker in LONG_GOAL_MARKERS)
        verb_count = sum(1 for verb in WORKFLOW_VERBS if re.search(rf"\b{re.escape(normalize_text(verb))}\b", text))
        connectors = sum(text.count(item) for item in (" sonra ", " ardindan ", " ve ", " then ", " and ", ","))
        if not explicit and not (verb_count >= 4 and connectors >= 2 and len(message) >= 100):
            return None
        return ActionMatch(score=120, arguments={"goal": message}, approved=True)

    async def execute(self, message: str, session_id: str, mode: str, voice: bool, match: ActionMatch) -> BrainResponse:
        if self.runtime.autonomy is None:
            raise RuntimeError("Long-horizon autonomy is not configured.")
        task = await self.runtime.autonomy.create(message, session_id, approved=match.approved)
        text = (
            f"Uzun görev başlatıldı: {task['id']}. Plan, doğrulama ve checkpoint akışı etkin."
            if is_turkish(message)
            else f"Long-horizon task started: {task['id']}. Planning, verification, and checkpoints are active."
        )
        intent = analyze_intent(message)
        self.runtime.brain.record_runtime_exchange(session_id, message, text, intent, mode)  # type: ignore[arg-type]
        return BrainResponse(text=text, session_id=session_id, provider="autonomy-v2", intent=intent)


def create_actions(runtime: LiveActionRuntime) -> List[LiveAction]:
    return [AutonomyGoalAction(runtime)]
