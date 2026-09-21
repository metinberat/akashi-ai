import re
from typing import List, Optional

from app.core.brain import BrainResponse
from app.core.intent import analyze_intent
from app.live.actions.base import LiveAction, LiveActionRuntime, is_turkish, normalize_text
from app.live.models import ActionMatch, LiveActionDefinition


class OpenAkashiProjectAction(LiveAction):
    definition = LiveActionDefinition(
        name="project.open_akashi",
        description="Open the configured AKASHI repository in allowlisted VS Code.",
        input_schema={"type": "object", "additionalProperties": False},
        risk="confirm",
        capabilities=("projects", "applications", "desktop"),
        examples=("AKASHI projesini aç.", "Open the AKASHI repository."),
    )

    def __init__(self, runtime: LiveActionRuntime) -> None:
        self.runtime = runtime

    def match(self, message: str) -> Optional[ActionMatch]:
        text = normalize_text(message)
        if re.search(r"\b(how do i|how to|why (?:does|is|would)|nasil)\b", text):
            return None
        if "akashi" not in text:
            return None
        project = any(word in text for word in ("proje", "project", "repository", "repo"))
        opening = bool(re.search(r"\b(ac|acar|baslat|open|launch)\b", text))
        return ActionMatch(score=110, arguments={}, approved=True) if project and opening else None

    async def execute(
        self,
        message: str,
        session_id: str,
        mode: str,
        voice: bool,
        match: ActionMatch,
    ) -> BrainResponse:
        project = self.runtime.settings.akashi_project_path
        if project is None:
            raise RuntimeError("AKASHI_PROJECT_PATH is not configured on Core.")
        result = await self.runtime.desktop.execute(
            "open_project", {"path": str(project)}, match.approved
        )
        data = result.get("data", {})
        if not isinstance(data, dict) or not data.get("confirmed"):
            raise RuntimeError("Project launch could not be confirmed.")
        text = (
            "AKASHI projesi VS Code'da açık."
            if is_turkish(message)
            else "AKASHI project is open in VS Code."
        )
        intent = analyze_intent(message)
        self.runtime.brain.record_runtime_exchange(
            session_id, message, text, intent, mode  # type: ignore[arg-type]
        )
        return BrainResponse(text=text, session_id=session_id, provider="windows-agent", intent=intent)


def create_actions(runtime: LiveActionRuntime) -> List[LiveAction]:
    return [OpenAkashiProjectAction(runtime)]
