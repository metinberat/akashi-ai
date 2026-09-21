import re
from typing import List, Optional

from app.core.brain import BrainResponse
from app.core.intent import analyze_intent
from app.live.actions.base import LiveAction, LiveActionRuntime, is_turkish, normalize_text
from app.live.models import ActionMatch, LiveActionDefinition


ALIASES = {
    "visual studio code": "vscode",
    "vs code": "vscode",
    "vscode": "vscode",
    "code": "vscode",
    "google chrome": "chrome",
    "chrome": "chrome",
    "edge": "edge",
    "browser": "browser",
    "tarayici": "browser",
    "terminal": "terminal",
    "powershell": "terminal",
    "spotify": "spotify",
}
LABELS = {
    "vscode": "VS Code",
    "chrome": "Chrome",
    "edge": "Edge",
    "browser": "Tarayıcı",
    "terminal": "Terminal",
    "spotify": "Spotify",
}


class OpenApplicationAction(LiveAction):
    definition = LiveActionDefinition(
        name="application.open",
        description="Launch one application from the Windows agent's discovered allowlist.",
        input_schema={
            "type": "object",
            "properties": {"application": {"type": "string", "maxLength": 40}},
            "required": ["application"],
            "additionalProperties": False,
        },
        risk="confirm",
        capabilities=("applications", "desktop"),
        examples=("VS Code'u aç.", "Open Chrome.", "Spotify'ı başlat."),
    )

    def __init__(self, runtime: LiveActionRuntime) -> None:
        self.runtime = runtime

    def match(self, message: str) -> Optional[ActionMatch]:
        text = normalize_text(message)
        if re.search(r"\b(how do i|how to|why (?:does|is|would)|nasil)\b", text):
            return None
        if any(word in text for word in ("proje", "project", "repository", "repo")):
            return None
        open_verb = re.search(r"\b(ac|acar|acabilir|baslat|open|launch|start)\b", text)
        if not open_verb:
            return None
        for alias in sorted(ALIASES, key=len, reverse=True):
            if re.search(rf"\b{re.escape(alias)}\b", text):
                return ActionMatch(
                    score=92,
                    arguments={"application": ALIASES[alias]},
                    approved=True,
                )
        prefix = text[:open_verb.start()].strip(" ,.!?'’\"")
        candidate_match = re.search(r"([a-z0-9._-]{2,40})(?:['’]?[uiuy]+)?$", prefix)
        if candidate_match:
            return ActionMatch(
                score=65,
                arguments={"application": candidate_match.group(1)},
                approved=True,
            )
        return None

    async def execute(
        self,
        message: str,
        session_id: str,
        mode: str,
        voice: bool,
        match: ActionMatch,
    ) -> BrainResponse:
        application = str(match.arguments["application"])
        result = await self.runtime.desktop.execute(
            "launch_application", {"application": application}, match.approved
        )
        data = result.get("data", {})
        if not isinstance(data, dict) or not data.get("confirmed"):
            raise RuntimeError("Application launch could not be confirmed.")
        label = LABELS.get(application, application)
        text = f"{label} açık." if is_turkish(message) else f"{label} is open."
        intent = analyze_intent(message)
        self.runtime.brain.record_runtime_exchange(
            session_id, message, text, intent, mode  # type: ignore[arg-type]
        )
        return BrainResponse(text=text, session_id=session_id, provider="windows-agent", intent=intent)

    def failure_text(self, message: str, error: Exception) -> str:
        if "allowlist" in str(error).casefold():
            return (
                "Uygulama bulunamadı veya güvenli kayıt listesinde değil. Uygulama registry'sini yeniden tara."
                if is_turkish(message)
                else "Application not found in the safe registry. Rescan installed applications."
            )
        return super().failure_text(message, error)


def create_actions(runtime: LiveActionRuntime) -> List[LiveAction]:
    return [OpenApplicationAction(runtime)]
