from typing import Sequence

from app.core.intent import Intent
from app.memory.base import MemoryMessage
from app.providers.base import AIProvider


class GeminiProvider(AIProvider):
    """Google GenAI SDK kullanan Gemini provider."""

    name = "gemini"

    def __init__(self, api_key: str, model_name: str) -> None:
        if not api_key or not api_key.strip():
            raise RuntimeError("GEMINI_API_KEY is missing.")

        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError(
                "Gemini support requires the google-genai package."
            ) from exc

        self._client = genai.Client(api_key=api_key.strip())
        self._types = types
        self._model_name = model_name

    async def generate(
        self,
        message: str,
        system_prompt: str,
        history: Sequence[MemoryMessage],
        intent: Intent,
    ) -> str:
        transcript = "\n".join(
            f"{item['role'].title()}: {item['content']}"
            for item in history
        )

        intent_name = getattr(intent, "value", str(intent))

        prompt_parts = [f"Detected user intent: {intent_name}"]

        if transcript:
            prompt_parts.append(
                f"Conversation so far:\n{transcript}"
            )

        prompt_parts.append(f"User message:\n{message}")

        prompt = "\n\n".join(prompt_parts)

        try:
            response = await self._client.aio.models.generate_content(
                model=self._model_name,
                contents=prompt,
                config=self._types.GenerateContentConfig(
                    system_instruction=system_prompt,
                ),
            )
        except Exception as exc:
            raise RuntimeError(
                f"Gemini request failed: {exc}"
            ) from exc

        text = getattr(response, "text", None)

        if not text:
            raise RuntimeError("Gemini returned an empty response.")

        return str(text).strip()