import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.core.absolute import AkashiCore, get_core
from app.core.auth import require_api_token
from app.memory.base import ConversationSummary, MemoryMessage
from app.memory.long_term import LongTermMemoryEntry, SensitiveMemoryError

router = APIRouter(
    prefix="/memory",
    tags=["memory"],
    dependencies=[Depends(require_api_token)],
)


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=8_000)
    category: str = Field(default="fact", min_length=1, max_length=40)
    source: str = Field(default="user", min_length=1, max_length=80)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    tags: List[str] = Field(default_factory=list, max_length=30)


class MemoryUpdate(BaseModel):
    content: Optional[str] = Field(default=None, min_length=1, max_length=8_000)
    category: Optional[str] = Field(default=None, min_length=1, max_length=40)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    tags: Optional[List[str]] = Field(default=None, max_length=30)


class MemoryRetrieve(BaseModel):
    query: str = Field(min_length=1, max_length=4_000)
    limit: int = Field(default=5, ge=1, le=20)
    categories: Optional[List[str]] = None


def _validate_session_id(session_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", session_id):
        raise HTTPException(status_code=422, detail="Invalid session_id.")
    return session_id


@router.get("")
async def list_memories(
    category: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    core: AkashiCore = Depends(get_core),
) -> dict[str, List[LongTermMemoryEntry]]:
    return {"memories": core.memory.list(category=category, query=query, limit=limit)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_memory(
    request: MemoryCreate,
    core: AkashiCore = Depends(get_core),
) -> LongTermMemoryEntry:
    try:
        return core.memory.create(**request.model_dump())
    except SensitiveMemoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/retrieve")
async def retrieve_memories(
    request: MemoryRetrieve,
    core: AkashiCore = Depends(get_core),
) -> dict[str, List[LongTermMemoryEntry]]:
    return {
        "memories": core.memory.retrieve(
            request.query,
            limit=request.limit,
            categories=request.categories,
        )
    }


@router.get("/conversations")
async def list_conversations(
    limit: int = Query(default=30, ge=1, le=100),
    core: AkashiCore = Depends(get_core),
) -> dict[str, List[ConversationSummary]]:
    return {"conversations": core.conversations.list_conversations(limit)}


@router.get("/conversations/{session_id}")
async def get_conversation(
    session_id: str,
    core: AkashiCore = Depends(get_core),
) -> dict[str, object]:
    validated = _validate_session_id(session_id)
    messages: List[MemoryMessage] = core.conversations.get_history(validated)
    if not messages:
        raise HTTPException(status_code=404, detail="Conversation was not found.")
    return {
        "session_id": validated,
        "messages": messages,
        "summary": core.conversations.get_summary(validated),
    }


@router.get("/{memory_id}")
async def get_memory(
    memory_id: str,
    core: AkashiCore = Depends(get_core),
) -> LongTermMemoryEntry:
    entry = core.memory.get(memory_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Memory was not found.")
    return entry


@router.patch("/{memory_id}")
async def update_memory(
    memory_id: str,
    request: MemoryUpdate,
    core: AkashiCore = Depends(get_core),
) -> LongTermMemoryEntry:
    try:
        entry = core.memory.update(
            memory_id,
            **request.model_dump(exclude_unset=True),
        )
    except SensitiveMemoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if entry is None:
        raise HTTPException(status_code=404, detail="Memory was not found.")
    return entry


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: str,
    core: AkashiCore = Depends(get_core),
) -> Response:
    if not core.memory.delete(memory_id):
        raise HTTPException(status_code=404, detail="Memory was not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
