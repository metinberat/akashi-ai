"""Remote presence HTTP + WebSocket surface (``akashi.remote/1``).

Three audiences, three kinds of credentials:

* Owner (AKASHI API token): pairing codes with chosen scopes, device list,
  grant changes, revocation, approvals, audit, owner realtime sessions.
* Device (no API token): pair with a one-time code, then per session: ask for a
  challenge and prove possession of the device key → short-lived session token.
* Session (session token, or the API token for owner sessions): realtime
  messages over WebSocket, or the HTTP transport (batched POST + long-poll GET)
  used where WebSocket is unavailable (the desktop IPC bridge, strict proxies).

Errors are JSON ``{"detail", "code", ...}``. Nothing here exposes a device
public key, a token hash or another device's session credential.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.approvals.center import ApprovalError
from app.core.absolute import AkashiCore, get_core
from app.core.auth import require_api_token
from app.core.config import get_settings
from app.remote import capabilities as caps
from app.remote import protocol, scopes
from app.remote.audit import AuditUnavailable
from app.remote.hub import RemoteError
from app.remote.sessions import RemoteSession, SessionAuthError
from app.spatial.assets import AssetError

owner_router = APIRouter(prefix="/remote", tags=["remote presence"], dependencies=[Depends(require_api_token)])
device_router = APIRouter(prefix="/remote", tags=["remote presence"])

AUTH_TIMEOUT = 5.0
POLL_MAX_WAIT = 25.0


def error(status: int, code: str, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse({"detail": message[:500], "code": code, **extra}, status_code=status, headers={"Cache-Control": "no-store"})


def failure(exc: Exception) -> JSONResponse:
    if isinstance(exc, RemoteError):
        return error(exc.status, exc.code, str(exc), **({"details": exc.details} if exc.details else {}))
    if isinstance(exc, SessionAuthError):
        return error(401, exc.code, str(exc))
    if isinstance(exc, scopes.ScopeError):
        return error(422, "bad_scopes", str(exc))
    if isinstance(exc, ApprovalError):
        return error(exc.status, exc.code, str(exc))
    if isinstance(exc, AuditUnavailable):
        return error(503, "audit_unavailable", str(exc))
    if isinstance(exc, KeyError):
        return error(404, "not_found", str(exc).strip("'\""))
    return error(422, "rejected", str(exc))


def _owner_token(authorization: Optional[str]) -> bool:
    expected = get_settings().api_token or ""
    scheme, _, token = (authorization or "").partition(" ")
    return (len(expected) >= 32 and scheme.lower() == "bearer" and len(token) <= 512
            and secrets.compare_digest(token.encode("utf-8"), expected.encode("utf-8")))


def _bearer(authorization: Optional[str]) -> Optional[str]:
    scheme, _, token = (authorization or "").partition(" ")
    return token if scheme.lower() == "bearer" and token else None


# Owner ------------------------------------------------------------------------------
class PairingCodeRequest(BaseModel):
    preset: Optional[str] = Field(default=None, max_length=40)
    scopes: Optional[List[str]] = Field(default=None, max_length=20)
    label: Optional[str] = Field(default=None, max_length=100)


class GrantsRequest(BaseModel):
    scopes: List[str] = Field(max_length=20)


class DecisionRequest(BaseModel):
    approve: bool


class OwnerSessionRequest(BaseModel):
    label: Optional[str] = Field(default=None, max_length=100)
    client: Dict[str, Any] = Field(default_factory=dict)
    capabilities: List[Any] = Field(default_factory=list, max_length=20)


@owner_router.get("/status")
async def status(core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    return core.remote.hub.status()


@owner_router.get("/catalog")
async def catalog() -> Dict[str, Any]:
    return {"protocol": protocol.PROTOCOL, "scopes": scopes.catalog(), "presets": scopes.PRESETS,
            "capabilities": [{"name": k, "description": v} for k, v in caps.CAPABILITIES.items()]}


@owner_router.post("/pairing-codes", status_code=201)
async def create_pairing_code(request: PairingCodeRequest, core: AkashiCore = Depends(get_core)):
    try:
        granted = scopes.from_preset(request.preset or "spatial-remote") if request.scopes is None else scopes.normalize(request.scopes)
        return core.remote.hub.create_pairing_code(granted, request.label)
    except Exception as exc:
        return failure(exc)


@owner_router.get("/devices")
async def list_devices(core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    hub = core.remote.hub
    now = hub.monotonic()
    live: Dict[str, List[Dict[str, Any]]] = {}
    for session in hub.sessions.live():
        live.setdefault(str(session.device.get("id")), []).append(session.public(now))
    devices = [dict(device, sessions=live.get(device["id"], [])) for device in core.devices.list_devices()
               if device.get("role") == "presence"]
    return {"devices": devices, "owner_sessions": live.get("owner", [])}


@owner_router.patch("/devices/{device_id}")
async def update_device(device_id: str, request: GrantsRequest, core: AkashiCore = Depends(get_core)):
    try:
        return {"device": await core.remote.hub.set_grants(device_id, request.scopes)}
    except ValueError as exc:
        if isinstance(exc, scopes.ScopeError):
            return failure(exc)
        return error(409, "not_presence_device", str(exc))
    except Exception as exc:
        return failure(exc)


@owner_router.delete("/devices/{device_id}")
async def revoke_device(device_id: str, core: AkashiCore = Depends(get_core)):
    device = core.devices.get(device_id)
    if device is None or device.get("role") != "presence":
        return error(404, "not_found", "Remote device was not found.")
    core.devices.revoke(device_id)
    closed = await core.remote.hub.revoke_device(device_id)
    try:
        core.remote.audit.record("device.revoked", by={"kind": "owner"}, device={"id": device_id, "name": device.get("name")},
                                 sessions_closed=closed)
    except AuditUnavailable:
        pass
    return {"status": "revoked", "sessions_closed": closed}


@owner_router.get("/providers")
async def providers(capability: Optional[str] = Query(default=None, max_length=40), core: AkashiCore = Depends(get_core)):
    registry = core.remote.hub.registry
    try:
        if capability is None:
            return {"devices": registry.summary(), "answer": registry.describe()}
        return {"providers": [p.public() for p in registry.providers(capability)], "answer": registry.describe(capability)}
    except caps.CapabilityError as exc:
        return error(422, "bad_capabilities", str(exc))


@owner_router.get("/approvals")
async def approvals(core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    return {"approvals": [item.public() for item in core.remote.approvals.pending()]}


@owner_router.post("/approvals/{approval_id}")
async def decide(approval_id: str, request: DecisionRequest, core: AkashiCore = Depends(get_core)):
    from datetime import datetime, timezone
    try:
        result = await core.remote.approvals.decide(approval_id, request.approve,
                                                    {"by": "owner", "device_id": "owner", "device_name": "AKASHI owner",
                                                     "at": datetime.now(timezone.utc).isoformat()})
    except Exception as exc:
        return failure(exc)
    core.remote.push_approvals()
    return result


@owner_router.get("/audit")
async def audit(after: int = Query(default=0, ge=0), limit: int = Query(default=200, ge=1, le=500),
                core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    return core.remote.audit.recent(after, limit)


@owner_router.post("/audit/verify")
async def verify_audit(core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    return core.remote.audit.verify()


@owner_router.post("/owner-sessions", status_code=201)
async def owner_session(request: OwnerSessionRequest, core: AkashiCore = Depends(get_core)):
    try:
        return await core.remote.hub.open_owner_session(request.label, request.client, request.capabilities)
    except Exception as exc:
        return failure(exc)


# Device -----------------------------------------------------------------------------
class PairRequest(BaseModel):
    code: str = Field(min_length=10, max_length=10)
    name: str = Field(min_length=1, max_length=100)
    device_type: str = Field(default="phone", min_length=1, max_length=40)
    public_key: Optional[Dict[str, Any]] = None


class ChallengeRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=64)


class SessionRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=64)
    nonce: Optional[str] = Field(default=None, max_length=64)
    signature: Optional[str] = Field(default=None, max_length=128)
    secret: Optional[str] = Field(default=None, max_length=256)
    scopes: Optional[List[str]] = Field(default=None, max_length=20)
    client: Dict[str, Any] = Field(default_factory=dict)
    capabilities: List[Any] = Field(default_factory=list, max_length=20)
    transport: Optional[str] = Field(default=None, max_length=20)


@device_router.post("/pair", status_code=201)
async def pair(request: PairRequest, core: AkashiCore = Depends(get_core)):
    try:
        return core.remote.hub.pair(request.code, request.name, request.device_type, request.public_key)
    except Exception as exc:
        return failure(exc)


@device_router.post("/challenge")
async def challenge(request: ChallengeRequest, core: AkashiCore = Depends(get_core)):
    try:
        return core.remote.hub.challenge(request.device_id)
    except Exception as exc:
        return failure(exc)


@device_router.post("/sessions", status_code=201)
async def open_session(request: SessionRequest, core: AkashiCore = Depends(get_core)):
    try:
        return await core.remote.hub.open_session(
            request.device_id, nonce=request.nonce, signature=request.signature, secret=request.secret,
            requested=request.scopes, client=request.client, capabilities=request.capabilities, transport=request.transport)
    except Exception as exc:
        return failure(exc)


# Session transports -----------------------------------------------------------------
def _session(core: AkashiCore, session_id: str, authorization: Optional[str]) -> RemoteSession:
    return core.remote.hub.authenticate(session_id, _bearer(authorization), owner_token_valid=_owner_token(authorization))


class Batch(BaseModel):
    messages: List[Any] = Field(max_length=protocol.MAX_BATCH)


@device_router.post("/sessions/{session_id}/messages")
async def post_messages(session_id: str, batch: Batch, authorization: Optional[str] = Header(default=None),
                        core: AkashiCore = Depends(get_core)):
    try:
        session = _session(core, session_id, authorization)
    except SessionAuthError as exc:
        return failure(exc)
    responses = await core.remote.hub.receive_batch(session, batch.messages, "http")
    return {"responses": responses, "sseq": session.outbox.sseq}


@device_router.get("/sessions/{session_id}/poll")
async def poll(session_id: str, after: int = Query(default=0, ge=0), wait: float = Query(default=20.0, ge=0, le=POLL_MAX_WAIT),
               authorization: Optional[str] = Header(default=None), core: AkashiCore = Depends(get_core)):
    try:
        session = _session(core, session_id, authorization)
    except SessionAuthError as exc:
        return failure(exc)
    session.transport = "http"
    core.remote.hub.sessions.touch(session)
    session.outbox.ack(after)
    messages, covered = session.outbox.after(after)
    if covered and not messages and session.state != "closed":
        messages = await session.outbox.wait(after, wait)
    return JSONResponse({"messages": messages, "sseq": session.outbox.sseq, "resync": not covered, "state": session.state},
                        headers={"Cache-Control": "no-store"})


@device_router.delete("/sessions/{session_id}")
async def close_session(session_id: str, authorization: Optional[str] = Header(default=None), core: AkashiCore = Depends(get_core)):
    try:
        session = _session(core, session_id, authorization)
    except SessionAuthError as exc:
        return failure(exc)
    await core.remote.hub.close_session(session, "client")
    return {"status": "closed"}


@device_router.get("/sessions/{session_id}/assets/{asset_id}")
async def asset(session_id: str, asset_id: str, authorization: Optional[str] = Header(default=None), core: AkashiCore = Depends(get_core)):
    try:
        session = _session(core, session_id, authorization)
    except SessionAuthError as exc:
        return failure(exc)
    if "spatial.view" not in session.scopes:
        return error(403, "forbidden", "This device may not view Spatial Lab assets.")
    try:
        data = await asyncio.to_thread(core.spatial.assets.content, asset_id)
    except AssetError as exc:
        return error(404 if exc.code == "not_found" else 422, exc.code, str(exc))
    except KeyError:
        return error(404, "not_found", "Asset was not found.")
    return Response(data, media_type="model/gltf-binary", headers={"Cache-Control": "private, max-age=3600"})


def _origin_allowed(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    return origin is None or origin in get_settings().cors_origins


@device_router.websocket("/ws")
async def remote_ws(websocket: WebSocket, core: AkashiCore = Depends(get_core)) -> None:
    """One realtime connection per session. Credentials travel in the first frame, never in the URL."""
    if not _origin_allowed(websocket):
        await websocket.close(code=4403)
        return
    await websocket.accept()
    hub = core.remote.hub
    send_lock = asyncio.Lock()

    async def send(message: Dict[str, Any]) -> None:
        async with send_lock:
            await websocket.send_text(json.dumps(message, ensure_ascii=False, separators=(",", ":")))

    try:
        first = json.loads(await asyncio.wait_for(websocket.receive_text(), AUTH_TIMEOUT))
        if not isinstance(first, dict) or first.get("type") != "auth":
            raise ValueError("auth frame expected")
        session = hub.authenticate(str(first.get("session_id")), first.get("token"))
    except SessionAuthError as exc:
        await send(protocol.error(exc.code, str(exc)))
        await websocket.close(code=4401)
        return
    except (asyncio.TimeoutError, ValueError, WebSocketDisconnect):
        try:
            await websocket.close(code=4401)
        except RuntimeError:
            pass
        return
    generation = session.data.get("ws_generation", 0) + 1
    session.data["ws_generation"] = generation
    session.transport = "websocket"
    if hub.sessions.touch(session):
        await hub._emit("resumed", session)
    resume = first.get("resume_after")
    resume = resume if isinstance(resume, int) and not isinstance(resume, bool) and resume >= 0 else None
    cursor = session.outbox.sseq
    resumed = False
    if resume is not None:
        _, covered = session.outbox.after(resume)
        if covered:
            cursor, resumed = resume, True
    await send({"v": 1, "kind": "session.welcome", "body": {"session_id": session.id, "scopes": sorted(session.scopes),
                                                             "resumed": resumed, "sseq": session.outbox.sseq,
                                                             "server_time_ms": hub.wall_ms(), **hub.sessions.config.public()}})
    if resume is not None and not resumed:
        await send({"v": 1, "sseq": session.outbox.sseq, "kind": "resync_required", "body": {"reason": "resume window passed"}})

    async def pump() -> None:
        nonlocal cursor
        while session.data.get("ws_generation") == generation:
            messages = await session.outbox.wait(cursor, 15.0)
            if session.data.get("ws_generation") != generation:
                return
            for message in messages:
                await send(message)
                cursor = message["sseq"]
            if messages:
                session.outbox.ack(cursor)
            if session.state == "closed":
                await asyncio.sleep(0.05)
                await websocket.close(code=4403 if session.close_reason == "revoked" else 4400)
                return

    pumping = asyncio.create_task(pump())
    try:
        while True:
            raw = await websocket.receive_text()
            if session.data.get("ws_generation") != generation:
                break  # replaced by a newer connection for this session
            response = await hub.receive(session, raw, "websocket")
            if response is not None:
                await send(response)
            if session.state == "closed":
                break
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        pumping.cancel()
        try:
            await pumping
        except (asyncio.CancelledError, Exception):
            pass
        if session.data.get("ws_generation") == generation:
            session.data["ws_generation"] = generation + 1  # detach; the session stays resumable until idle timeout
        try:
            await websocket.close()
        except RuntimeError:
            pass
