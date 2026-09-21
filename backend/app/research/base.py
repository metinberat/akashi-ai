from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class ResearchSource:
    title: str
    url: str
    snippet: str
    provider: str
    relevance: float


class ResearchProvider(ABC):
    name: str

    @abstractmethod
    async def search(self, query: str, limit: int = 5) -> List[ResearchSource]:
        raise NotImplementedError

