from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.absolute import AkashiCore, get_core
from app.core.auth import require_api_token


router = APIRouter(
    prefix="/computer",
    tags=["computer"],
    dependencies=[Depends(require_api_token)],
)


class ComputerTaskRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)
    session_id: str = Field(default="desktop", min_length=1, max_length=128)
    task_id: Optional[str] = Field(default=None, min_length=8, max_length=128)
    approved: bool = False


@router.post("/tasks", status_code=status.HTTP_202_ACCEPTED)
async def run_computer_task(
    request: ComputerTaskRequest,
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    try:
        return await core.computer.run(
            request.goal,
            request.session_id,
            approved=request.approved,
            task_id=request.task_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/tasks")
async def list_computer_tasks(
    limit: int = Query(default=50, ge=1, le=200),
    core: AkashiCore = Depends(get_core),
) -> Dict[str, List[Dict[str, Any]]]:
    return {"tasks": core.computer.store.list(limit)}


@router.get("/tasks/{session_id}")
async def get_computer_task(
    session_id: str,
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    item = core.computer.store.get(session_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Computer session was not found.")
    return item


@router.post("/tasks/{session_id}/cancel")
async def cancel_computer_task(
    session_id: str,
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    return {"session_id": session_id, "cancelled": await core.computer.cancel(session_id)}
