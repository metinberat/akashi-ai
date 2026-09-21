from dataclasses import dataclass
from typing import Any, Dict, Literal, Tuple


RiskLevel = Literal["safe", "confirm", "restricted"]


@dataclass(frozen=True)
class LiveActionDefinition:
    name: str
    description: str
    input_schema: Dict[str, Any]
    risk: RiskLevel
    capabilities: Tuple[str, ...]
    examples: Tuple[str, ...]


@dataclass(frozen=True)
class ActionMatch:
    score: int
    arguments: Dict[str, Any]
    approved: bool = False

