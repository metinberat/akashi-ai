import secrets
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.absolute import AkashiCore, get_core
from app.core.auth import require_api_token
from app.events.hub import event_hub
from app.phone.service import PhoneConfigurationError
from app.phone.store import CallDirection, CallState


router = APIRouter(
    prefix="/phone",
    tags=["phone"],
    dependencies=[Depends(require_api_token)],
)
worker_router = APIRouter(prefix="/phone/worker", tags=["phone worker"])


class OutboundCallRequest(BaseModel):
    destination: str = Field(min_length=8, max_length=16)


class WorkerCallEvent(BaseModel):
    call_id: str = Field(min_length=8, max_length=128)
    state: CallState
    direction: CallDirection = "inbound"
    room_name: str = Field(default="", max_length=128)
    caller_number: str = Field(default="unknown", max_length=64)
    callee_number: Optional[str] = Field(default=None, max_length=64)
    transcript_role: Optional[Literal["caller", "assistant"]] = None
    transcript_text: Optional[str] = Field(default=None, max_length=4_000)
    transcript_final: bool = True
    result: Optional[str] = Field(default=None, max_length=500)
    error: Optional[str] = Field(default=None, max_length=500)


def require_phone_worker(
    worker_token: Optional[str] = Header(default=None, alias="X-Akashi-Phone-Worker-Token"),
    core: AkashiCore = Depends(get_core),
) -> None:
    expected = core.settings.phone_worker_token
    if not expected or len(expected) < 32:
        raise HTTPException(status_code=503, detail="Phone worker authentication is not configured.")
    if not worker_token or len(worker_token) > 512 or not secrets.compare_digest(worker_token, expected):
        raise HTTPException(status_code=401, detail="Invalid phone worker credential.")


@router.get("/status")
async def status(core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    return core.phone.status()


@router.get("/calls")
async def list_calls(
    limit: int = Query(default=30, ge=1, le=100),
    active_only: bool = False,
    core: AkashiCore = Depends(get_core),
) -> Dict[str, List[Dict[str, Any]]]:
    return {"calls": core.phone_calls.list(limit=limit, active_only=active_only)}


@router.get("/calls/{call_id}")
async def get_call(call_id: str, core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    item = core.phone_calls.get(call_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Phone call was not found.")
    return item


@router.post("/calls/{call_id}/hangup")
async def hangup(call_id: str, core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    try:
        return await core.phone.hangup(call_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PhoneConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="LiveKit could not end the call.") from exc


@router.post("/outbound", status_code=202)
async def outbound(request: OutboundCallRequest, core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    try:
        return await core.phone.start_outbound(request.destination)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PhoneConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="LiveKit could not start the outbound call.") from exc


@worker_router.post("/events", dependencies=[Depends(require_phone_worker)])
async def worker_event(
    request: WorkerCallEvent,
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    item = core.phone_calls.update(
        request.call_id,
        request.state,
        direction=request.direction,
        room_name=request.room_name,
        caller_number=request.caller_number,
        callee_number=request.callee_number,
        transcript_role=request.transcript_role,
        transcript_text=request.transcript_text,
        transcript_final=request.transcript_final,
        result=request.result,
        error=request.error,
    )
    await event_hub.publish(
        "phone.call.state",
        {"call_id": request.call_id, "state": request.state, "status": request.state},
    )
    return item

