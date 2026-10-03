"""Spatial Lab tools for AKASHI's typed ToolRegistry (``/tools``, tasks, agents).

All tools are scene-bounded: they never touch files, the desktop or the browser.
Removing an object needs the separate ``spatial.confirm`` tool, which carries the
``confirm`` risk level and therefore requires explicit approval through the
existing AKASHI approval path.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.history.engine import CommandRejected
from app.spatial.model import summarize
from app.spatial.references import Clarification
from app.spatial.service import RequestInvalid, SpatialLabService
from app.tools.base import Tool, ToolDefinition

SESSION = {"type": "string"}


def _session_id(service: SpatialLabService, arguments: Dict[str, Any]) -> str:
    session_id = arguments.get("session_id")
    if session_id:
        return str(session_id)
    active = service.active_session()
    if active is None:
        raise ValueError("No Spatial Lab session is open. Open Spatial Lab or pass session_id.")
    return active.id


def _slim(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": result["status"],
        "revision": result.get("revision"),
        "targets": result.get("targets", []),
        "notes": result.get("notes", []),
        "events": [{"seq": e["seq"], "command": e["command"]["type"], "summary": e["summary"]} for e in result.get("events", [])],
        **({"token": result["token"], "question": result["question"]} if result["status"] == "confirmation_required" else {}),
    }


class SpatialSceneTool(Tool):
    definition = ToolDefinition(
        name="spatial.scene",
        description="Read the current Spatial Lab scene: objects, selection, transforms, FORM provenance and clips.",
        input_schema={"type": "object", "properties": {"session_id": SESSION}},
        result_schema={"type": "object", "properties": {"session": {"type": "object"}, "scene": {"type": "object"}}},
        risk="safe",
    )

    def __init__(self, service: SpatialLabService) -> None:
        self.service = service

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        session = self.service.session(_session_id(self.service, arguments))
        snapshot = self.service.snapshot(session)
        return {"session": snapshot["session"], "scene": summarize(snapshot["state"])}


class SpatialCommandTool(Tool):
    definition = ToolDefinition(
        name="spatial.command",
        description=("Apply one validated Spatial Lab request (the same contract used by gestures and UI), e.g. "
                     "{\"type\":\"object.transform\",\"target\":{\"ref\":\"selected\"},\"mode\":\"scale\",\"factor\":1.25}. "
                     "Scene-only; removals return a confirmation token."),
        input_schema={"type": "object", "required": ["request"],
                      "properties": {"session_id": SESSION, "request": {"type": "object"}}},
        result_schema={"type": "object", "properties": {"status": {"type": "string"}}},
        risk="safe",
    )

    def __init__(self, service: SpatialLabService) -> None:
        self.service = service

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        session_id = _session_id(self.service, arguments)
        try:
            result = await self.service.submit(session_id, arguments["request"],
                                               {"kind": "tool", "provider": "tool:spatial.command"})
        except Clarification as exc:
            return {"status": "clarification", "question": exc.question, "candidates": exc.candidates}
        except (CommandRejected, RequestInvalid) as exc:
            raise ValueError(str(exc)) from exc
        return _slim(result)


class SpatialInterpretTool(Tool):
    definition = ToolDefinition(
        name="spatial.interpret",
        description="Interpret and apply a Turkish or English Spatial Lab instruction (\"make it bigger\", \"iskeleti göster\").",
        input_schema={"type": "object", "required": ["text"],
                      "properties": {"session_id": SESSION, "text": {"type": "string"}, "execute": {"type": "boolean"}}},
        result_schema={"type": "object", "properties": {"understood": {"type": "boolean"}, "reply": {"type": "string"}}},
        risk="safe",
    )

    def __init__(self, service: SpatialLabService) -> None:
        self.service = service

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        text = str(arguments.get("text") or "").strip()
        if not text or len(text) > 500:
            raise ValueError("text must be 1-500 characters.")
        outcome = await self.service.interpret(_session_id(self.service, arguments), text, provider="tool:spatial.interpret",
                                               execute=arguments.get("execute", True) is not False)
        outcome["results"] = [_slim(r) for r in outcome.get("results", [])]
        return outcome


class SpatialConfirmTool(Tool):
    definition = ToolDefinition(
        name="spatial.confirm",
        description="Confirm a pending destructive Spatial Lab change (for example removing an object).",
        input_schema={"type": "object", "required": ["token"], "properties": {"session_id": SESSION, "token": {"type": "string"}}},
        result_schema={"type": "object", "properties": {"status": {"type": "string"}}},
        risk="confirm",
    )

    def __init__(self, service: SpatialLabService) -> None:
        self.service = service

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        try:
            result = await self.service.confirm(_session_id(self.service, arguments), str(arguments["token"]))
        except CommandRejected as exc:
            raise ValueError(str(exc)) from exc
        return _slim(result)


class FormLibraryTool(Tool):
    definition = ToolDefinition(
        name="spatial.form_library",
        description="List FORM projects, or one project's versions, through the read-only FORM adapter.",
        input_schema={"type": "object", "properties": {"project_id": {"type": "string"}}},
        result_schema={"type": "object", "properties": {"available": {"type": "boolean"}}},
        risk="safe",
    )

    def __init__(self, service: SpatialLabService) -> None:
        self.service = service

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        status = self.service.form.status()
        if not status["available"]:
            return {"available": False, "reason": status["reason"]}
        project: Optional[str] = arguments.get("project_id")
        if project:
            return {"available": True, "versions": self.service.form.versions(project)}
        return {"available": True, "projects": self.service.form.projects()}


def spatial_tools(service: SpatialLabService):
    return [SpatialSceneTool(service), SpatialCommandTool(service), SpatialInterpretTool(service),
            SpatialConfirmTool(service), FormLibraryTool(service)]
