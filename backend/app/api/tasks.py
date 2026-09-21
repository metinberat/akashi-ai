from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.absolute import AkashiCore, get_core
from app.core.auth import require_api_token

router = APIRouter(
    prefix="/tasks",
    tags=["tasks"],
    dependencies=[Depends(require_api_token)],
)


class TaskStepRequest(BaseModel):
    tool: str = Field(min_length=1, max_length=100)
    arguments: Dict[str, Any] = Field(default_factory=dict)


class TaskCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    steps: List[TaskStepRequest] = Field(min_length=1, max_length=25)
    approved: bool = False


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_task(
    request: TaskCreateRequest,
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    try:
        return await core.tasks.create(
            request.title,
            [step.model_dump() for step in request.steps],
            approved=request.approved,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
async def list_tasks(
    limit: int = Query(default=100, ge=1, le=500),
    core: AkashiCore = Depends(get_core),
) -> Dict[str, List[Dict[str, Any]]]:
    return {"tasks": core.tasks.store.list(limit)}


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    task = core.tasks.store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task was not found.")
    return task


@router.post("/{task_id}/approve")
async def approve_task(
    task_id: str,
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    try:
        return await core.tasks.approve(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    try:
        return await core.tasks.cancel(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
