from abc import ABC, abstractmethod
from typing import Literal, Optional, TypedDict

from app.core.intent import Intent


class MemoryMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str
    intent: Optional[Intent]
    timestamp: str


class MemoryStore(ABC):
    """Interface for swappable conversation memory backends."""

    @abstractmethod
    def get_history(self, session_id: str) -> list[MemoryMessage]:
        raise NotImplementedError

    @abstractmethod
    def append(
        self,
        session_id: str,
        role: Literal["user", "assistant"],
        content: str,
        intent: Optional[Intent] = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def clear(self, session_id: str) -> None:
        raise NotImplementedError
