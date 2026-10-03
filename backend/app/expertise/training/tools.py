import asyncio
from app.tools.base import Tool, ToolDefinition
from .contracts import TrainingRequest


class TrainYourselfTool(Tool):
    definition = ToolDefinition(name="character.train_yourself", description="Explicitly start bounded synthetic character-production practice using stored recipes. Not professional mastery or model fine-tuning.",
        input_schema=TrainingRequest.model_json_schema(), result_schema={"type": "object"}, risk="confirm")

    def __init__(self, service):
        self.service = service

    async def execute(self, arguments):
        run = await asyncio.to_thread(self.service.training.create, TrainingRequest.model_validate(arguments))
        return await self.service.training_host.start(run["id"])


class TrainingStatusTool(Tool):
    definition = ToolDefinition(name="character.training_status", description="Inspect durable training exercises, best checkpoints and measured synthetic lessons.",
        input_schema={"type": "object", "required": ["run_id"], "additionalProperties": False, "properties": {"run_id": {"type": "string", "maxLength": 128}}},
        result_schema={"type": "object"}, risk="safe")

    def __init__(self, service):
        self.service = service

    async def execute(self, arguments):
        return {"run": await asyncio.to_thread(self.service.training.repository.get, arguments["run_id"]),
                "exercises": await asyncio.to_thread(self.service.training.repository.exercises, arguments["run_id"])}


class ProductionRecipeTool(Tool):
    definition = ToolDefinition(name="character.production_recipe", description="Inspect observed production relations separately from inferred historical workflow and hypotheses. Source data is never executable.",
        input_schema={"type": "object", "required": ["asset_id"], "additionalProperties": False, "properties": {"asset_id": {"type": "string", "maxLength": 128}}},
        result_schema={"type": "object"}, risk="safe")

    def __init__(self, service):
        self.service = service

    async def execute(self, arguments):
        return await asyncio.to_thread(self.service.recipes.for_asset, arguments["asset_id"])


class TrainingControlTool(Tool):
    definition = ToolDefinition(name="character.training_control", description="Explicit pause/resume/cancel of synthetic training. Resume never starts camera/microphone or external applications.",
        input_schema={"type": "object", "required": ["run_id", "command"], "additionalProperties": False,
                      "properties": {"run_id": {"type": "string", "maxLength": 128}, "command": {"type": "string", "enum": ["pause", "resume", "cancel"]}}},
        result_schema={"type": "object"}, risk="confirm")

    def __init__(self, service):
        self.service = service

    async def execute(self, arguments):
        if arguments["command"] == "resume":
            return await self.service.training_host.start(arguments["run_id"])
        return await asyncio.to_thread(self.service.training.repository.request, arguments["run_id"], arguments["command"])


class ApplyLearnedMethodTool(Tool):
    definition = ToolDefinition(name="character.apply_learned_method", description="Create a protected improvement workshop from learned workflow parameters; it is a proposal, not a success claim or automatic professional-knowledge promotion.",
        input_schema={"type": "object", "required": ["asset_id", "method_version"], "additionalProperties": False,
                      "properties": {"asset_id": {"type": "string", "maxLength": 128}, "method_version": {"type": "string", "maxLength": 128}}},
        result_schema={"type": "object"}, risk="confirm")

    def __init__(self, service):
        self.service = service

    async def execute(self, arguments):
        return await asyncio.to_thread(self.service.propose_learned_method, arguments["asset_id"], arguments["method_version"])
