from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.absolute import AkashiCore, get_core
from app.core.auth import require_api_token
from app.events.hub import event_hub

router = APIRouter(
    prefix="/devices",
    tags=["devices"],
    dependencies=[Depends(require_api_token)],
)
pairing_router = APIRouter(prefix="/devices", tags=["device pairing"])


class PairRequest(BaseModel):
    code: str = Field(min_length=10, max_length=10)
    name: str = Field(min_length=1, max_length=100)
    device_type: str = Field(default="desktop", min_length=1, max_length=40)
    capabilities: List[str] = Field(default_factory=list, max_length=100)


class DeviceActionRequest(BaseModel):
    action: str = Field(min_length=1, max_length=80)
    arguments: Dict[str, Any] = Field(default_factory=dict)
    approved: bool = False


class DeviceActionResult(BaseModel):
    ok: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = Field(default=None, max_length=1_000)


async def require_device(
    authorization: Optional[str] = Header(default=None),
    device_id: Optional[str] = Header(default=None, alias="X-Akashi-Device-Id"),
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    scheme, separator, token = (authorization or "").partition(" ")
    if not device_id or not separator or scheme.casefold() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Missing device credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    device = core.devices.authenticate(device_id, token)
    if device is None or device.get("role", "agent") != "agent":
        # Remote presence devices authenticate through /remote; they can never
        # poll or complete Windows Agent actions.
        raise HTTPException(
            status_code=401,
            detail="Invalid or revoked device credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return device


@router.post("/pairing-codes")
async def create_pairing_code(core: AkashiCore = Depends(get_core)) -> Dict[str, str]:
    return core.devices.create_pairing_code()


@pairing_router.post("/pair")
async def pair_device(
    request: PairRequest,
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    try:
        device, token = core.devices.pair(
            request.code,
            request.name,
            request.device_type,
            request.capabilities,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    await event_hub.publish("device.paired", {"device": device})
    return {"device": device, "device_token": token}


@router.get("")
async def list_devices(core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    return {"devices": core.devices.list_devices()}


@router.delete("/{device_id}")
async def revoke_device(
    device_id: str,
    core: AkashiCore = Depends(get_core),
) -> Dict[str, str]:
    if not core.devices.revoke(device_id):
        raise HTTPException(status_code=404, detail="Device was not found.")
    # A remote presence device loses its live sessions immediately, not at the next sweep.
    await core.remote.hub.revoke_device(device_id)
    await event_hub.publish("device.revoked", {"device_id": device_id})
    return {"status": "revoked"}


@router.post("/{device_id}/actions", status_code=202)
async def queue_device_action(
    device_id: str,
    request: DeviceActionRequest,
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    try:
        action = core.devices.queue_action(
            device_id,
            request.action,
            request.arguments,
            request.approved,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await event_hub.publish("device.action.queued", {"action": action})
    return action


@router.get("/actions/{action_id}")
async def get_device_action(
    action_id: str,
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    action = core.devices.get_action(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Device action was not found.")
    return action


@pairing_router.get("/agent/actions")
async def poll_device_actions(
    limit: int = Query(default=5, ge=1, le=10),
    device: Dict[str, Any] = Depends(require_device),
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    actions = core.devices.poll_actions(device["id"], limit)
    return {"actions": actions}


@pairing_router.post("/agent/actions/{action_id}/result")
async def complete_device_action(
    action_id: str,
    request: DeviceActionResult,
    device: Dict[str, Any] = Depends(require_device),
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    try:
        action = core.devices.complete_action(
            device["id"],
            action_id,
            request.ok,
            request.result,
            request.error,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await event_hub.publish("device.action.completed", {"action": action})
    return action


@pairing_router.post("/agent/heartbeat")
async def device_heartbeat(
    device: Dict[str, Any] = Depends(require_device),
) -> Dict[str, Any]:
    await event_hub.publish("device.heartbeat", {"device_id": device["id"]})
    return {"status": "ok", "device": device}
