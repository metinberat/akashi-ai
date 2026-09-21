from dataclasses import asdict
from typing import Any, Dict, List

from app.tools.base import Tool
from app.tools.validation import validate, validate_arguments


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        name = tool.definition.name
        if not name or name in self._tools:
            raise ValueError(f"Tool '{name}' is already registered or invalid.")
        self._tools[name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool '{name}'.") from exc

    def definitions(self) -> List[Dict[str, Any]]:
        return [asdict(self._tools[name].definition) for name in sorted(self._tools)]

    async def invoke(
        self,
        name: str,
        arguments: Dict[str, Any],
        approved: bool = False,
    ) -> Dict[str, Any]:
        tool = self.get(name)
        validate_arguments(arguments, tool.definition.input_schema)
        risk = tool.definition.risk
        if risk == "restricted":
            raise PermissionError("Restricted tools cannot be invoked.")
        if risk == "confirm" and not approved:
            raise PermissionError("This tool requires explicit approval.")
        result = await tool.execute(dict(arguments))
        validate(result, tool.definition.result_schema, "result", strict=False)
        return {
            "tool": name,
            "risk": risk,
            "ok": True,
            "data": result,
        }
