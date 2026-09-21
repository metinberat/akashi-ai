from typing import Any, Dict

from app.files.service import FileIntelligenceService
from app.memory.long_term import JSONLongTermMemory
from app.research.service import ResearchService
from app.tools.base import Tool, ToolDefinition
from app.devices.store import DeviceStore


class MemorySearchTool(Tool):
    definition = ToolDefinition(
        name="memory.search",
        description="Retrieve relevant durable AKASHI memories.",
        input_schema={
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
        },
        result_schema={"type": "object", "properties": {"memories": {"type": "array"}}},
        risk="safe",
    )

    def __init__(self, memory: JSONLongTermMemory) -> None:
        self._memory = memory

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        limit = int(arguments.get("limit", 5))
        return {"memories": self._memory.retrieve(query, limit=limit)}


class MemoryCreateTool(Tool):
    definition = ToolDefinition(
        name="memory.create",
        description="Store one explicit, durable non-secret memory.",
        input_schema={
            "type": "object",
            "required": ["content"],
            "properties": {
                "content": {"type": "string"},
                "category": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
        },
        result_schema={"type": "object", "properties": {"memory": {"type": "object"}}},
        risk="confirm",
    )

    def __init__(self, memory: JSONLongTermMemory) -> None:
        self._memory = memory

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        tags = arguments.get("tags")
        if tags is not None and not isinstance(tags, list):
            raise ValueError("tags must be an array")
        entry = self._memory.create(
            content=str(arguments.get("content") or ""),
            category=str(arguments.get("category") or "fact"),
            source="tool:memory.create",
            tags=[str(item) for item in (tags or [])],
        )
        return {"memory": entry}


class FileReadTool(Tool):
    definition = ToolDefinition(
        name="files.read",
        description="Read a previously uploaded, validated text file by id.",
        input_schema={
            "type": "object",
            "required": ["file_id"],
            "properties": {"file_id": {"type": "string"}, "max_chars": {"type": "integer"}},
        },
        result_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        risk="safe",
    )

    def __init__(self, files: FileIntelligenceService) -> None:
        self._files = files

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        file_id = str(arguments.get("file_id") or "")
        max_chars = int(arguments.get("max_chars", 50_000))
        record = self._files.get(file_id)
        if record is None:
            raise FileNotFoundError("Uploaded file was not found.")
        return {
            "file": record,
            "text": self._files.get_text(file_id, max_chars=max_chars),
        }


class ResearchTool(Tool):
    definition = ToolDefinition(
        name="research.web",
        description="Run real source-backed normal or deep web research.",
        input_schema={
            "type": "object",
            "required": ["question"],
            "properties": {
                "question": {"type": "string"},
                "mode": {"type": "string", "enum": ["normal", "deep"]},
            },
        },
        result_schema={"type": "object", "properties": {"sources": {"type": "array"}}},
        risk="safe",
    )

    def __init__(self, research: ResearchService) -> None:
        self._research = research

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        mode = str(arguments.get("mode") or "normal")
        if mode not in {"normal", "deep"}:
            raise ValueError("mode must be normal or deep")
        return await self._research.run(
            str(arguments.get("question") or ""),
            mode=mode,  # type: ignore[arg-type]
        )


class DeviceStatusTool(Tool):
    definition = ToolDefinition(
        name="devices.status",
        description="List paired devices and their online state.",
        input_schema={"type": "object", "properties": {}},
        result_schema={"type": "object", "properties": {"devices": {"type": "array"}}},
        risk="safe",
    )

    def __init__(self, devices: DeviceStore) -> None:
        self._devices = devices

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return {"devices": self._devices.list_devices()}


class DeviceActionTool(Tool):
    definition = ToolDefinition(
        name="devices.action",
        description="Queue an approved structured action for a paired desktop.",
        input_schema={
            "type": "object",
            "required": ["device_id", "action"],
            "properties": {
                "device_id": {"type": "string"},
                "action": {"type": "string"},
                "arguments": {"type": "object"},
            },
        },
        result_schema={"type": "object", "properties": {"action": {"type": "object"}}},
        risk="confirm",
    )

    def __init__(self, devices: DeviceStore) -> None:
        self._devices = devices

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        payload = arguments.get("arguments") or {}
        if not isinstance(payload, dict):
            raise ValueError("arguments must be an object")
        action = self._devices.queue_action(
            device_id=str(arguments.get("device_id") or ""),
            action=str(arguments.get("action") or ""),
            arguments=payload,
            approved=True,
        )
        return {"action": action}
