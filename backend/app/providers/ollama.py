import asyncio
import json
from typing import Sequence
from urllib import error, request

from app.core.intent import Intent
from typing import Optional
from app.memory.base import MemoryMessage
from app.providers.base import AIProvider


class OllamaProvider(AIProvider):
    """Local Ollama provider used by Akashi."""

    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model_name: str,
        timeout_seconds: float = 180.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model_name = model_name
        self._timeout_seconds = timeout_seconds

    async def generate(
        self,
        message: str,
        system_prompt: str,
        history: Sequence[MemoryMessage],
        intent: Intent,
    ) -> str:
        return await asyncio.to_thread(
            self._generate_sync,
            message,
            system_prompt,
            history,
            intent,
        )

    def _generate_sync(
        self,
        message: str,
        system_prompt: str,
        history: Sequence[MemoryMessage],
        intent: Intent,
        images: Optional[Sequence[str]] = None,
    ) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    f"{system_prompt}\n\n"
                    f"Detected intent: {intent}\n"
                    "The latest user message alone determines the response language."
                ),
            }
        ]

        for item in history:
            role = item.get("role")
            content = item.get("content", "").strip()

            if role in {"user", "assistant"} and content:
                messages.append(
                    {
                        "role": role,
                        "content": content,
                    }
                )

        messages.append(
            {
                "role": "user",
                "content": message,
            }
        )

        payload = {
            "model": self._model_name,
            "messages": messages,
            "stream": False,
            "keep_alive": "15m",
            "options": {
                "temperature": 0.2,
            },
        }

        if images:
            messages[-1]["images"] = [value.partition(",")[2] for value in images]
        body = json.dumps(payload).encode("utf-8")

        api_request = request.Request(
            url=f"{self._base_url}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(
                api_request,
                timeout=self._timeout_seconds,
            ) as response:
                result = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            raise RuntimeError(
                f"Model provider returned HTTP {exc.code}."
            ) from exc
        except error.URLError as exc:
            raise RuntimeError(
                "Ollama could not be reached. Make sure Ollama is running."
            ) from exc
        except TimeoutError as exc:
            raise RuntimeError(
                "Ollama response timed out."
            ) from exc

        text = result.get("message", {}).get("content", "").strip()

        if not text:
            raise RuntimeError("Ollama returned an empty response.")

        return text

    async def generate_with_images(self, message, system_prompt, history, intent, images) -> str:
        return await asyncio.to_thread(self._generate_sync, message, system_prompt, history, intent, images)
