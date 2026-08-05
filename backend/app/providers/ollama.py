import asyncio
import json
from typing import Sequence
from urllib import error, request

from app.core.intent import Intent
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
    ) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    f"{system_prompt}\n\n"
                    "Runtime facts:\n"
                    "- Host application: Akashi AI / ABSOLUTE Engine\n"
                    "- AI provider: Ollama\n"
                    f"- Active model: {self._model_name}\n"
                    "- Execution location: the user's own computer\n"
                    "- Internet/API dependency: none for this response\n\n"
                    "ABSOLUTE Engine is the host application, not the AI "
                    "provider or model. When asked how you are running, "
                    "state that you run locally through Ollama using the "
                    f"{self._model_name} model.\n"
                    f"Detected intent: {intent}\n"
                    "Always answer in the user's language."
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
                "temperature": 0.7,
            },
        }

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
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Ollama returned HTTP {exc.code}: {detail}"
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
