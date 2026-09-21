from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.absolute import AkashiCore, get_core
from app.core.auth import require_api_token


router = APIRouter(
    prefix="/intelligence",
    tags=["intelligence"],
    dependencies=[Depends(require_api_token)],
)


class DiscoveryRequest(BaseModel):
    categories: Optional[List[str]] = None
    per_feed: int = Field(default=4, ge=1, le=10)


class StatusRequest(BaseModel):
    status: Literal[
        "new", "reviewed", "dismissed", "watching",
        "approved_for_test", "approved_for_maintenance",
    ]


class ScheduleStateRequest(BaseModel):
    enabled: bool


@router.get("/items")
async def items(
    category: Optional[str] = Query(default=None, max_length=100),
    status: Optional[str] = Query(default=None, max_length=100),
    limit: int = Query(default=100, ge=1, le=500),
    core: AkashiCore = Depends(get_core),
) -> List[Dict[str, Any]]:
    return core.intelligence_store.list_items(category, status, limit)


@router.post("/discover")
async def discover(
    request: DiscoveryRequest,
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    return await core.intelligence.discover(request.categories, request.per_feed)


@router.patch("/items/{item_id}/status")
async def update_status(
    item_id: str,
    request: StatusRequest,
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    try:
        return core.intelligence_store.set_status(item_id, request.status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/briefs")
async def create_brief(core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    return core.intelligence.create_daily_brief()


@router.get("/briefs")
async def briefs(
    limit: int = Query(default=30, ge=1, le=90),
    core: AkashiCore = Depends(get_core),
) -> List[Dict[str, Any]]:
    return core.intelligence_store.list_briefs(limit)


@router.get("/maintenance")
async def maintenance(core: AkashiCore = Depends(get_core)) -> List[Dict[str, Any]]:
    return core.intelligence_store.list_maintenance()


@router.get("/schedules")
async def schedules(core: AkashiCore = Depends(get_core)) -> List[Dict[str, Any]]:
    return core.schedule_store.list()


@router.patch("/schedules/{job_id}")
async def schedule_state(
    job_id: str,
    request: ScheduleStateRequest,
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    try:
        return core.schedule_store.set_enabled(job_id, request.enabled)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/schedules/{job_id}/run")
async def run_schedule(
    job_id: str,
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    try:
        return await core.scheduler.run_now(job_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

