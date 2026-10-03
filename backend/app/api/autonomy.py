from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.absolute import AkashiCore, get_core
from app.core.auth import require_api_token


router = APIRouter(prefix="/autonomy", tags=["autonomy"], dependencies=[Depends(require_api_token)])


class GoalRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=8000)
    session_id: str = Field(default="desktop", min_length=1, max_length=128)
    approved: bool = False


class ResumeRequest(BaseModel):
    approved: Optional[bool] = None


class KnowledgeMetadata(BaseModel):
    category: Literal["official_documentation", "technical_article", "tutorial", "community_discussion", "internal_note", "project_documentation", "task_experience"] = "internal_note"
    authority: Literal["official", "author_reported", "community", "internal", "unknown"] = "unknown"
    confidence: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)
    version: Optional[str] = Field(default=None, max_length=200)


class KnowledgeRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=500000)
    source: Optional[str] = Field(default=None, max_length=2000)
    kind: str = Field(default="note", min_length=1, max_length=60)
    metadata: KnowledgeMetadata = Field(default_factory=KnowledgeMetadata)


@router.post("/tasks", status_code=status.HTTP_202_ACCEPTED)
async def create_goal(request: GoalRequest, core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    try:
        return await core.autonomy.create(request.goal, request.session_id, request.approved)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/tasks")
async def list_goals(limit: int = Query(default=50, ge=1, le=200), core: AkashiCore = Depends(get_core)) -> Dict[str, List[Dict[str, Any]]]:
    return {"tasks": core.autonomy.store.list(limit)}


@router.get("/tasks/{task_id}")
async def get_goal(task_id: str, core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    task = core.autonomy.store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Autonomy task was not found.")
    return task


@router.post("/tasks/{task_id}/resume")
async def resume_goal(task_id: str, request: ResumeRequest, core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    try:
        return await core.autonomy.resume(task_id, request.approved)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/cancel")
async def cancel_goal(task_id: str, core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    try:
        return await core.autonomy.cancel(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/skills")
async def list_skills(limit: int = Query(default=100, ge=1, le=300), core: AkashiCore = Depends(get_core)) -> Dict[str, List[Dict[str, Any]]]:
    return {"skills": core.autonomy_skills.list(limit)}


@router.post("/skills/{skill_id}/activate")
async def activate_skill(skill_id: str, core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    try:
        return core.autonomy_skills.activate(skill_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/knowledge")
async def ingest_knowledge(request: KnowledgeRequest, core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    try:
        return core.autonomy_knowledge.ingest(request.title, request.text, request.source, request.kind, request.metadata.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/knowledge")
async def search_knowledge(query: str = Query(min_length=2, max_length=500), limit: int = Query(default=6, ge=1, le=20), core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    return {"results": core.autonomy_knowledge.search(query, limit)}
