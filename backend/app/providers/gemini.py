import asyncio
from typing import Sequence

from app.core.intent import Intent
from app.memory.base import MemoryMessage
from app.providers.base import AIProvider


class GeminiProvider(AIProvider):
    """Gemini adapter. Imported only when Gemini is selected."""

    name = "gemini"

    def __init__(self, api_key: str, model_name: str) -> None:
        try:
            import google.generativeai as genai
        except ImportError as exc:
            raise RuntimeError(
                "Gemini support requires the google-generativeai package."
            ) from exc

        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(model_name)

    async def generate(
        self,
        message: str,
        system_prompt: str,
        history: Sequence[MemoryMessage],
        intent: Intent,
    ) -> str:
        transcript = "\n".join(
            f"{item['role'].title()}: {item['content']}" for item in history
        )
        prompt_parts = [system_prompt]
        if transcript:
            prompt_parts.append(f"Conversation so far:\n{transcript}")
        prompt_parts.append(f"User: {message}\nAssistant:")
        prompt = "\n\n".join(prompt_parts)

        response = await asyncio.to_thread(self._model.generate_content, prompt)
        text = getattr(response, "text", None)
        if not text:
            raise RuntimeError("Gemini returned an empty response.")
        return str(text).strip()
