from typing import Sequence

from app.core.intent import Intent
from app.memory.base import MemoryMessage
from app.providers.base import AIProvider


class MockProvider(AIProvider):
    """Local Akashi-style provider used without credentials."""

    name = "mock"

    async def generate(
        self,
        message: str,
        system_prompt: str,
        history: Sequence[MemoryMessage],
        intent: Intent,
    ) -> str:
        previous_turns = len(history) // 2
        continuity = (
            f"\n\nContext: I found {previous_turns} relevant earlier "
            "conversation turn(s)."
            if previous_turns
            else ""
        )
        responses = {
            "study": (
                f"Let's turn this into a focused study session: {message}\n\n"
                "1. Define the exact learning goal.\n"
                "2. Review the core idea in plain language.\n"
                "3. Work through one guided example.\n"
                "4. Test recall with three short questions.\n"
                "5. Finish with a brief summary and next step."
            ),
            "code": (
                f"Engineering read: {message}\n\n"
                "Approach:\n"
                "- Clarify the expected input, output, and constraints.\n"
                "- Isolate the smallest testable component.\n"
                "- Implement it behind a clean interface.\n"
                "- Verify the happy path, edge cases, and failure behavior.\n\n"
                "Share the relevant code or error output and I can make this concrete."
            ),
            "research": (
                f"Research brief: {message}\n\n"
                "- Frame a precise question.\n"
                "- Separate primary evidence from commentary.\n"
                "- Compare credible sources and note disagreements.\n"
                "- Record uncertainty, dates, and assumptions.\n"
                "- Synthesize findings into a concise conclusion."
            ),
            "planning": (
                f"Let's make the plan executable: {message}\n\n"
                "1. Define the outcome and deadline.\n"
                "2. Split it into milestones.\n"
                "3. Choose the smallest useful first action.\n"
                "4. Identify risks and dependencies.\n"
                "5. Set a review point and adjust."
            ),
            "casual": (
                f"Hey — I'm here. You said: \"{message}\"\n\n"
                "What would make this conversation useful or interesting for you?"
            ),
            "unknown": (
                f"I hear you: \"{message}\"\n\n"
                "I can help turn that into a clear question, plan, explanation, "
                "or next action."
            ),
        }
        return responses[intent] + continuity
