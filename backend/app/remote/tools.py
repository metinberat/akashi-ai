"""Read-only remote presence tools for AKASHI's typed ToolRegistry.

Deciding an approval is deliberately not a tool: a decision must come from a
person on an authorized surface, never from an agent step.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.remote.capabilities import CAPABILITIES, CapabilityError
from app.tools.base import Tool, ToolDefinition


class RemoteDevicesTool(Tool):
    definition = ToolDefinition(
        name="remote.devices",
        description="List connected remote devices and their live capabilities, or which devices can provide one capability "
                    f"({', '.join(sorted(CAPABILITIES))}).",
        input_schema={"type": "object", "properties": {"capability": {"type": "string", "enum": sorted(CAPABILITIES)}}},
        result_schema={"type": "object", "properties": {"devices": {"type": "array"}, "providers": {"type": "array"},
                                                        "answer": {"type": "string"}}},
        risk="safe",
    )

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        registry = self.runtime.hub.registry
        capability = arguments.get("capability")
        try:
            if capability:
                return {"providers": [p.public() for p in registry.providers(capability)], "answer": registry.describe(capability)}
        except CapabilityError as exc:
            raise ValueError(str(exc)) from exc
        return {"devices": registry.summary(), "answer": registry.describe()}


class PendingApprovalsTool(Tool):
    definition = ToolDefinition(
        name="approvals.pending",
        description="List pending approvals across AKASHI (Spatial Lab confirmations, tasks, autonomy) with why each needs approval.",
        input_schema={"type": "object", "properties": {}},
        result_schema={"type": "object", "properties": {"approvals": {"type": "array"}}},
        risk="safe",
    )

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return {"approvals": [item.public() for item in self.runtime.approvals.pending()]}


def remote_tools(runtime: Any) -> List[Tool]:
    return [RemoteDevicesTool(runtime), PendingApprovalsTool(runtime)]
