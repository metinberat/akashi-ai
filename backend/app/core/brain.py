from dataclasses import dataclass
from typing import List, Literal, Optional

from app.core.formatter import ResponseFormatter
from app.core.intent import Intent, analyze_intent
from app.core.persona import build_system_prompt
from app.memory.base import MemoryMessage, MemoryStore
from app.providers.base import AIProvider


@dataclass(frozen=True)
class BrainResponse:
    text: str
    session_id: str
    provider: str
    intent: Intent


@dataclass(frozen=True)
class BrainContext:
    system_prompt: str
    user_message: str
    session_id: str
    mode: Literal["private", "public"]
    intent: Intent
    memory: List[MemoryMessage]


class AkashiBrain:
    """Coordinates intent, persona, memory, providers, and response formatting."""

    def __init__(
        self,
        provider: AIProvider,
        memory: MemoryStore,
        formatter: Optional[ResponseFormatter] = None,
    ) -> None:
        self.provider = provider
        self.memory = memory
        self.formatter = formatter or ResponseFormatter()

    def build_context(
        self,
        message: str,
        session_id: str,
        mode: Literal["private", "public"],
        intent: Intent,
    ) -> BrainContext:
        history = self.memory.get_history(session_id) if mode == "private" else []
        relevant_memory = [
            entry for entry in history
            if entry.get("intent") in (None, intent)
        ][-10:]
        context_details = (
            "Current request context:\n"
            f"- session_id: {session_id}\n"
            f"- mode: {mode}\n"
            f"- detected_intent: {intent}\n"
            f"- user_message: {message}"
        )
        return BrainContext(
            system_prompt=f"{build_system_prompt(mode)}\n\n{context_details}",
            user_message=message,
            session_id=session_id,
            mode=mode,
            intent=intent,
            memory=relevant_memory,
        )

    async def respond(
        self,
        message: str,
        session_id: str = "default",
        mode: Literal["private", "public"] = "private",
    ) -> BrainResponse:
        clean_message = message.strip()
        intent = analyze_intent(clean_message)
        context = self.build_context(
            message=clean_message,
            session_id=session_id,
            mode=mode,
            intent=intent,
        )
        raw_text = await self.provider.generate(
            message=context.user_message,
            system_prompt=context.system_prompt,
            history=context.memory,
            intent=context.intent,
        )
        text = self.formatter.format(raw_text)

        self.memory.append(
            session_id, role="user", content=clean_message, intent=intent
        )
        self.memory.append(
            session_id, role="assistant", content=text, intent=intent
        )
        return BrainResponse(
            text=text,
            session_id=session_id,
            provider=self.provider.name,
            intent=intent,
        )
