"""Spatial Lab HTTP API (authenticated, scene-bounded).

Errors carry a human ``detail`` string plus a machine ``code`` and, for
clarifications, ``question`` and ``candidates`` so clients can ask the user.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.absolute import AkashiCore, get_core
from app.core.auth import require_api_token
from app.history.engine import CommandRejected, HistoryConflict, HistoryFull, ReplayDivergence
from app.spatial.assets import AssetError
from app.spatial.form_library import FormLibraryError
from app.spatial.references import Clarification
from app.spatial.service import RequestInvalid, SpatialLabService
from app.spatial.session import SessionCorrupted

router = APIRouter(prefix="/spatial", tags=["spatial"], dependencies=[Depends(require_api_token)])
MAX_UPLOAD = 20 * 1024 * 1024  # bounded by the desktop IPC request budget
BUSY_CODES = {"object_busy", "lease_expired", "lease_mismatch", "scene_changed", "confirmation_expired"}


def service(core: AkashiCore = Depends(get_core)) -> SpatialLabService:
    return core.spatial


def error(status: int, code: str, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse({"detail": message[:500], "code": code, **extra}, status_code=status,
                        headers={"Cache-Control": "no-store"})


async def guarded(operation: Callable[[], Awaitable[Any]]) -> Any:
    try:
        return await operation()
    except Clarification as exc:
        return error(409, exc.code, exc.question, kind="clarification", question=exc.question, candidates=exc.candidates)
    except CommandRejected as exc:
        return error(409 if exc.code in BUSY_CODES else 422, exc.code, str(exc), kind="rejected", details=exc.details)
    except RequestInvalid as exc:
        return error(422, "invalid_request", str(exc), kind="invalid")
    except AssetError as exc:
        return error(404 if exc.code == "not_found" else 422, exc.code, str(exc), kind="asset")
    except FormLibraryError as exc:
        return error(404 if exc.code in {"not_found", "no_project", "no_version"} else 503, "form_" + exc.code, str(exc), kind="form")
    except SessionCorrupted as exc:
        return error(423, "session_corrupted", str(exc), kind="integrity")
    except (HistoryFull, HistoryConflict, ReplayDivergence) as exc:
        return error(409, type(exc).__name__, str(exc), kind="history")
    except KeyError as exc:
        return error(404, "not_found", str(exc.args[0]) if exc.args else "Not found.")


def _response(result: Dict[str, Any], spatial: SpatialLabService, session_id: str) -> Dict[str, Any]:
    body = {k: v for k, v in result.items() if k != "request"}
    body["snapshot"] = spatial.snapshot(spatial.session(session_id))
    return body


class SessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(default="Spatial Lab", min_length=1, max_length=80)


class CommandInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: Dict[str, Any]
    origin: Dict[str, Any] = Field(default_factory=lambda: {"kind": "ui", "provider": "ui"})
    confirmed: bool = False


class ConfirmInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accept: bool = True


class InterpretInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=500)
    execute: bool = True
    voice: bool = False


class LeaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_id: str = Field(max_length=32)
    origin: Literal["gesture", "ui", "remote"] = "gesture"


class AnchorInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    position: List[float] = Field(min_length=3, max_length=3)
    confidence: float = Field(ge=0, le=1)


class PresenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    anchors: Dict[Literal["left_hand", "right_hand"], AnchorInput] = Field(default_factory=dict)


@router.get("/capabilities")
async def capabilities(spatial: SpatialLabService = Depends(service)) -> Dict[str, Any]:
    return spatial.capabilities()


@router.get("/metrics")
async def metrics(spatial: SpatialLabService = Depends(service)) -> Dict[str, Any]:
    return spatial.metrics()


@router.get("/sessions")
async def list_sessions(spatial: SpatialLabService = Depends(service)) -> Dict[str, Any]:
    return {"sessions": spatial.sessions.list()}


@router.post("/sessions", status_code=201)
async def create_session(value: SessionInput, spatial: SpatialLabService = Depends(service)):
    return spatial.create_session(value.label)


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, since: Optional[int] = Query(default=None, ge=0), client: bool = False,
                      spatial: SpatialLabService = Depends(service)):
    async def run():
        session = spatial.session(session_id)
        if since is not None and since == session.history.revision:
            if client:
                session.touch_client()
                spatial.active_session_id = session.id
            snapshot = spatial.snapshot(session)
            return {"changed": False, "session": snapshot["session"]}
        return {"changed": True, **spatial.snapshot(session, client=client)}
    return await guarded(run)


@router.post("/sessions/{session_id}/commands")
async def submit(session_id: str, value: CommandInput, spatial: SpatialLabService = Depends(service)):
    async def run():
        result = await spatial.submit(session_id, value.request, value.origin, confirmed=value.confirmed)
        return _response(result, spatial, session_id)
    return await guarded(run)


@router.post("/sessions/{session_id}/confirmations/{token}")
async def confirm(session_id: str, token: str, value: ConfirmInput, spatial: SpatialLabService = Depends(service)):
    async def run():
        return _response(await spatial.confirm(session_id, token, value.accept), spatial, session_id)
    return await guarded(run)


@router.post("/sessions/{session_id}/interpret")
async def interpret(session_id: str, value: InterpretInput, spatial: SpatialLabService = Depends(service)):
    async def run():
        outcome = await spatial.interpret(session_id, value.text, execute=value.execute, voice=value.voice)
        for result in outcome.get("results", []):
            result.pop("request", None)
        outcome["snapshot"] = spatial.snapshot(spatial.session(session_id))
        return outcome
    return await guarded(run)


@router.post("/sessions/{session_id}/leases", status_code=201)
async def begin_lease(session_id: str, value: LeaseInput, spatial: SpatialLabService = Depends(service)):
    async def run():
        return spatial.begin_lease(session_id, value.object_id, value.origin)
    return await guarded(run)


@router.post("/sessions/{session_id}/leases/{lease_id}/renew")
async def renew_lease(session_id: str, lease_id: str, spatial: SpatialLabService = Depends(service)):
    async def run():
        return spatial.renew_lease(session_id, lease_id)
    return await guarded(run)


@router.delete("/sessions/{session_id}/leases/{lease_id}")
async def end_lease(session_id: str, lease_id: str, spatial: SpatialLabService = Depends(service)):
    async def run():
        return {"ended": spatial.end_lease(session_id, lease_id)}
    return await guarded(run)


@router.post("/sessions/{session_id}/presence")
async def presence(session_id: str, value: PresenceInput, spatial: SpatialLabService = Depends(service)):
    async def run():
        spatial.presence(session_id, {k: v.model_dump() for k, v in value.anchors.items()})
        return {"accepted": True}
    return await guarded(run)


@router.get("/sessions/{session_id}/events")
async def events(session_id: str, after: int = Query(default=0, ge=0), limit: int = Query(default=200, ge=1, le=500),
                 spatial: SpatialLabService = Depends(service)):
    async def run():
        return spatial.events_page(session_id, after, limit)
    return await guarded(run)


@router.post("/sessions/{session_id}/replay/verify")
async def verify(session_id: str, spatial: SpatialLabService = Depends(service)):
    async def run():
        return spatial.verify_replay(session_id)
    return await guarded(run)


@router.get("/sessions/{session_id}/states/{seq}")
async def state_at(session_id: str, seq: int, spatial: SpatialLabService = Depends(service)):
    async def run():
        try:
            return spatial.state_at(session_id, seq)
        except ValueError as exc:
            return error(404, "not_found", str(exc))
    return await guarded(run)


@router.get("/assets")
async def assets(spatial: SpatialLabService = Depends(service)) -> Dict[str, Any]:
    return {"assets": spatial.assets.list()}


@router.post("/assets", status_code=201)
async def upload(file: UploadFile = File(...), spatial: SpatialLabService = Depends(service)):
    async def run():
        try:
            data = await file.read(MAX_UPLOAD + 1)
        finally:
            await file.close()
        if len(data) > MAX_UPLOAD:
            return error(413, "too_large", "Uploads are limited to 20 MiB in Spatial Lab V1; FORM artifacts are read in place.")
        return await asyncio.to_thread(spatial.assets.register_upload, data, file.filename or "upload.glb")
    return await guarded(run)


@router.get("/assets/{asset_id}")
async def asset(asset_id: str, spatial: SpatialLabService = Depends(service)):
    async def run():
        record = spatial.assets.record(asset_id)
        record.pop("location", None)
        return record
    return await guarded(run)


@router.get("/assets/{asset_id}/content")
async def asset_content(asset_id: str, spatial: SpatialLabService = Depends(service)):
    async def run():
        data = await asyncio.to_thread(spatial.assets.content, asset_id)
        return Response(data, media_type="model/gltf-binary",
                        headers={"Cache-Control": "private, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff",
                                 "X-Akashi-Asset-Sha256": asset_id})
    return await guarded(run)


@router.get("/form/projects")
async def form_projects(spatial: SpatialLabService = Depends(service)):
    async def run():
        status = spatial.form.status()
        if not status["available"]:
            return {"available": False, "reason": status["reason"], "projects": []}
        return {"available": True, "projects": spatial.form.projects()}
    return await guarded(run)


@router.get("/form/projects/{project_id}/versions")
async def form_versions(project_id: str, spatial: SpatialLabService = Depends(service)):
    async def run():
        return {"versions": spatial.form.versions(project_id)}
    return await guarded(run)
