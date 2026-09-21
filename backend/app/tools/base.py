from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Literal

RiskLevel = Literal["safe", "confirm", "restricted"]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: Dict[str, Any]
    result_schema: Dict[str, Any]
    risk: RiskLevel


class Tool(ABC):
    definition: ToolDefinition

    @abstractmethod
    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

