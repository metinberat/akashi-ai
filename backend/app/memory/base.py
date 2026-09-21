from abc import ABC, abstractmethod
from typing import Literal, Optional

from typing_extensions import TypedDict

from app.core.intent import Intent


class MemoryMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str
    intent: Optional[Intent]
    timestamp: str


class ConversationSummary(TypedDict):
    session_id: str
    title: str
    excerpt: str
    message_count: int
    last_updated: str


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

    def get_summary(self, session_id: str) -> Optional[str]:
        """Return compressed older context when a backend supports it."""
        return None

    @abstractmethod
    def list_conversations(self, limit: int = 30) -> list[ConversationSummary]:
        """Return bounded metadata for resumable private conversations."""
        raise NotImplementedError
