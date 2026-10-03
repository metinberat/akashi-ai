import asyncio
from app.tools.base import Tool, ToolDefinition
from .contracts import BuildRequest
from .reference import ReferenceIntelligence


class BuildCharacterTool(Tool):
    definition = ToolDefinition(
        name="character.build",
        description="Create and explicitly run a headless production objective. Local stylized construction, rig, surface layers and spatial HUD; professional/reference fidelity remains separately evaluated.",
        input_schema=BuildRequest.model_json_schema(),
        result_schema={"type": "object"},
        risk="confirm",
    )

    def __init__(self, host, router):
        self.host, self.router = host, router

    async def execute(self, arguments):
        request, evidence = await ReferenceIntelligence(self.router).resolve(
            BuildRequest.model_validate(arguments)
        )
        job = await asyncio.to_thread(self.host.engine.create, request, evidence)
        return await self.host.start(job["id"])


class InspectProductionTool(Tool):
    definition = ToolDefinition(
        name="character.production_status",
        description="Inspect actual production checkpoints, measured candidates and DCC evidence; never infer success from dispatch.",
        input_schema={
            "type": "object",
            "required": ["job_id"],
            "additionalProperties": False,
            "properties": {"job_id": {"type": "string", "maxLength": 128}},
        },
        result_schema={"type": "object"},
        risk="safe",
    )

    def __init__(self, host):
        self.host = host

    async def execute(self, arguments):
        repo = self.host.engine.repository
        return {
            "job": await asyncio.to_thread(repo.get, arguments["job_id"]),
            "trials": await asyncio.to_thread(repo.trials, arguments["job_id"]),
        }


class PracticeProductionTool(Tool):
    definition = ToolDefinition(
        name="character.practice_production",
        description="Explicitly practice varied local full-character geometry/surface/rig construction. Numeric scope only; DCC execution remains a separate approved objective.",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "count": {"type": "integer", "minimum": 1, "maximum": 12},
                "seed": {"type": "integer", "minimum": 0, "maximum": 2147380000},
            },
        },
        result_schema={"type": "object"},
        risk="confirm",
    )

    def __init__(self, engine):
        self.engine = engine

    async def execute(self, arguments):
        return await asyncio.to_thread(
            self.engine.practice, arguments.get("count", 3), arguments.get("seed", 57)
        )


class ControlProductionTool(Tool):
    definition = ToolDefinition(
        name="character.production_control",
        description="Explicit production pause/cancel/resume/reconcile. Resume never blindly replays ambiguous external effects.",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["job_id", "command"],
            "properties": {
                "job_id": {"type": "string", "maxLength": 128},
                "command": {
                    "type": "string",
                    "enum": ["pause", "cancel", "resume", "reconcile"],
                },
            },
        },
        result_schema={"type": "object"},
        risk="confirm",
    )

    def __init__(self, host):
        self.host = host

    async def execute(self, arguments):
        key, command = arguments["job_id"], arguments["command"]
        if command in {"pause", "cancel"}:
            return await asyncio.to_thread(
                self.host.engine.repository.request, key, command
            )
        if command == "reconcile":
            return await self.host.reconcile(key)
        return await self.host.start(key)
