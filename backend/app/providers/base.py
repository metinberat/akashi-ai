from abc import ABC, abstractmethod
from typing import Sequence

from app.core.intent import Intent
from app.memory.base import MemoryMessage


class AIProvider(ABC):
    """Interface implemented by every model provider."""

    name: str

    async def generate_with_images(
        self, message: str, system_prompt: str, history: Sequence[MemoryMessage],
        intent: Intent, images: Sequence[str],
    ) -> str:
        raise ValueError("This provider does not accept images.")

    @abstractmethod
    async def generate(
        self,
        message: str,
        system_prompt: str,
        history: Sequence[MemoryMessage],
        intent: Intent,
    ) -> str:
        raise NotImplementedError
