from typing import Any, Dict, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import time
import uuid
import httpx
from typing import Optional

from app.core.absolute import AkashiCore, get_core
from app.core.auth import require_api_token
from app.events.hub import event_hub

router = APIRouter(
    prefix="/research",
    tags=["research"],
    dependencies=[Depends(require_api_token)],
)
_runs: Dict[str, Dict[str, Any]] = {}


class ResearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=5_000)
    mode: Literal["normal", "deep"] = "normal"
    request_id: Optional[uuid.UUID] = None


@router.post("")
async def research(
    request: ResearchRequest,
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    request_id = str(request.request_id or uuid.uuid4())
    if request_id in _runs:
        raise HTTPException(status_code=409, detail="Research request ID already exists.")
    # Personal, single-worker progress cache. No question or source text retained here.
    for key, item in list(_runs.items()):
        if time.monotonic() - item["updated"] > 600:
            _runs.pop(key, None)
    if len(_runs) >= 100:
        raise HTTPException(status_code=429, detail="Research capacity reached. Retry later.")
    async def progress(state: str, payload: Dict[str, Any]) -> None:
        _runs[request_id] = {"state": state, "source_count": payload.get("source_count"), "updated": time.monotonic()}
        await event_hub.publish(
            "research.progress",
            {"request_id": request_id, "state": state, **payload},
        )

    try:
        return await core.research.run(request.question, request.mode, progress)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Research source returned HTTP {exc.response.status_code}. Check the configured research provider; SearXNG or DuckDuckGo topic search can be configured server-side.") from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Research provider could not complete the request.",
        ) from exc


@router.get("/runs/{request_id}")
async def research_progress(request_id: uuid.UUID) -> Dict[str, Any]:
    item = _runs.get(str(request_id))
    if item is None:
        return {"state": "queued"}
    return {key: value for key, value in item.items() if key != "updated"}


@router.get("/status")
async def research_status(core: AkashiCore = Depends(get_core)) -> Dict[str, str]:
    return {"provider": core.research.provider.name, "status": "ready"}
