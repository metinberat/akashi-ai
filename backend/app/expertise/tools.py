"""Thin host tools. Character-specific algorithms never enter generic Core/Tasks."""
import asyncio
from typing import Any, Dict

from app.expertise.blender_workflow import BlenderWorkshopWorkflow
from app.expertise.workshop.contracts import WorkshopRequest
from app.tools.base import Tool, ToolDefinition


class ImproveCharacterTool(Tool):
    definition = ToolDefinition(name="character.improve", description="Run non-destructive measured character improvement on an ingested asset; artistic quality is not certified.",
        input_schema={"type": "object", "required": ["asset_id"], "additionalProperties": False,
                      "properties": {"asset_id": {"type": "string", "maxLength": 128}, "objective": {"type": "string", "maxLength": 1000}, "max_attempts": {"type": "integer", "minimum": 1, "maximum": 16}}},
        result_schema={"type": "object", "properties": {"improvement": {"type": "object"}}}, risk="confirm")

    def __init__(self, workshop):
        self.workshop = workshop

    async def execute(self, arguments: Dict[str, Any]):
        request = WorkshopRequest.model_validate(arguments)
        job = await asyncio.to_thread(self.workshop.create, request)
        try:
            return {"improvement": await asyncio.to_thread(self.workshop.run, job["id"])}
        except asyncio.CancelledError:
            await asyncio.to_thread(self.workshop.repository.cancel, job["id"])
            raise


class InspectCharacterImprovementTool(Tool):
    definition = ToolDefinition(name="character.improvement_status", description="Inspect durable improvement checkpoints, quality evidence and best version.",
        input_schema={"type": "object", "required": ["job_id"], "additionalProperties": False, "properties": {"job_id": {"type": "string", "maxLength": 128}}},
        result_schema={"type": "object", "properties": {"improvement": {"type": "object"}, "versions": {"type": "array"}}}, risk="safe")

    def __init__(self, workshop):
        self.workshop = workshop

    async def execute(self, arguments: Dict[str, Any]):
        return {"improvement": await asyncio.to_thread(self.workshop.repository.get, arguments["job_id"]),
                "versions": await asyncio.to_thread(self.workshop.repository.versions, arguments["job_id"])}


class MaterializeCharacterTool(Tool):
    definition = ToolDefinition(name="character.materialize_blender", description="Apply best weights to a NEW Blender artifact through the fixed authenticated Windows Agent, read back and verify real deformation; source remains unchanged.",
        input_schema={"type": "object", "required": ["job_id", "project", "output_directory"], "additionalProperties": False,
                      "properties": {"job_id": {"type": "string", "maxLength": 128}, "project": {"type": "string", "maxLength": 2000}, "output_directory": {"type": "string", "maxLength": 2000}}},
        result_schema={"type": "object", "properties": {"evidence": {"type": "object"}}}, risk="confirm")

    def __init__(self, workshop, desktop):
        self.workflow = BlenderWorkshopWorkflow(desktop, workshop)

    async def execute(self, arguments: Dict[str, Any]):
        return await self.workflow.materialize(arguments["job_id"], arguments["project"], arguments["output_directory"])


class RefineCharacterTool(Tool):
    definition = ToolDefinition(name="character.refine_blender", description="Improve, apply to new Blender artifacts and test saved deformation; actual quality failure replans within the original attempt budget, never retries ambiguous transport failure.",
        input_schema={"type": "object", "required": ["job_id", "project", "output_directory"], "additionalProperties": False,
                      "properties": {"job_id": {"type": "string", "maxLength": 128}, "project": {"type": "string", "maxLength": 2000},
                                     "output_directory": {"type": "string", "maxLength": 2000}, "max_cycles": {"type": "integer", "minimum": 1, "maximum": 3}}},
        result_schema={"type": "object", "properties": {"status": {"type": "string"}, "cycles": {"type": "array"}}}, risk="confirm")

    def __init__(self, workshop, desktop):
        self.workflow = BlenderWorkshopWorkflow(desktop, workshop)

    async def execute(self, arguments: Dict[str, Any]):
        try:
            return await self.workflow.refine(arguments["job_id"], arguments["project"], arguments["output_directory"], arguments.get("max_cycles", 3))
        except asyncio.CancelledError:
            await asyncio.to_thread(self.workflow.workshop.repository.cancel, arguments["job_id"])
            raise
