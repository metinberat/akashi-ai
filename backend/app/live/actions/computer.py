import re
from typing import List, Optional

from app.core.brain import BrainResponse
from app.core.intent import analyze_intent
from app.live.actions.base import LiveAction, LiveActionRuntime, is_turkish, normalize_text
from app.live.models import ActionMatch, LiveActionDefinition


DESKTOP_TERMS = {
    "bilgisayar", "desktop", "windows", "pencere", "window", "ekran", "screen",
    "tikla", "click", "surukle", "drag", "kaydir", "scroll", "yaz", "type",
    "discord", "chrome", "edge", "browser", "tarayici", "uygulama", "application",
    "dosya", "file", "klasor", "folder", "sekme", "tab", "vscode", "vs code",
}
ACTION_TERMS = {
    "ac", "open", "bul", "find", "git", "go", "gec", "switch", "kapat", "close",
    "tikla", "click", "yaz", "type", "surukle", "drag", "kaydir", "scroll", "don", "return",
}
CONNECTORS = (" sonra ", " and then ", " then ", " ardindan ", " ardından ", ",", ";")


class ComputerGoalAction(LiveAction):
    definition = LiveActionDefinition(
        name="computer.goal",
        description="Execute a bounded multi-step Windows task through observe-plan-act-verify.",
        input_schema={
            "type": "object",
            "properties": {"goal": {"type": "string", "maxLength": 4000}},
            "required": ["goal"],
            "additionalProperties": False,
        },
        risk="confirm",
        capabilities=("desktop", "vision", "mouse", "keyboard", "windows", "files"),
        examples=(
            "Discord'u aç, ilgili pencereye geç ve X kişisini bul.",
            "Open the browser, inspect the project page, then return to VS Code.",
        ),
    )

    def __init__(self, runtime: LiveActionRuntime) -> None:
        self.runtime = runtime

    def match(self, message: str) -> Optional[ActionMatch]:
        text = normalize_text(message)
        has_desktop = any(term in text for term in DESKTOP_TERMS)
        has_action = any(re.search(rf"\b{re.escape(term)}\b", text) for term in ACTION_TERMS)
        multi_step = sum(text.count(connector.strip()) for connector in CONNECTORS) > 0
        explicit_input = any(term in text for term in ("tikla", "click", "surukle", "drag", "kaydir", "scroll", "pencere", "window"))
        if not has_desktop or not has_action or not (multi_step or explicit_input):
            return None
        return ActionMatch(score=98 if multi_step else 76, arguments={"goal": message}, approved=True)

    async def execute(
        self,
        message: str,
        session_id: str,
        mode: str,
        voice: bool,
        match: ActionMatch,
    ) -> BrainResponse:
        if self.runtime.computer is None:
            raise RuntimeError("Computer agent is not configured.")
        result = await self.runtime.computer.run(message, session_id, approved=match.approved)
        status = str(result.get("status") or "unknown")
        summary = str(result.get("summary") or "")
        if not summary:
            summary = (
                f"Bilgisayar görevi {status}." if is_turkish(message)
                else f"Computer task {status}."
            )
        intent = analyze_intent(message)
        self.runtime.brain.record_runtime_exchange(
            session_id, message, summary, intent, mode  # type: ignore[arg-type]
        )
        return BrainResponse(
            text=summary,
            session_id=session_id,
            provider="computer-agent",
            intent=intent,
        )


def create_actions(runtime: LiveActionRuntime) -> List[LiveAction]:
    return [ComputerGoalAction(runtime)]
