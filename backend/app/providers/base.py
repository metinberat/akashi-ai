from abc import ABC, abstractmethod
from typing import Sequence

from app.core.intent import Intent
from app.memory.base import MemoryMessage


class AIProvider(ABC):
    """Interface implemented by every model provider."""

    name: str

    @abstractmethod
    async def generate(
        self,
        message: str,
        system_prompt: str,
        history: Sequence[MemoryMessage],
        intent: Intent,
    ) -> str:
        raise NotImplementedError
