import json
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse

from app.core.auth import require_api_token
from app.events.hub import event_hub

router = APIRouter(
    prefix="/events",
    tags=["events"],
    dependencies=[Depends(require_api_token)],
)


@router.get("/recent")
async def recent_events(response: Response, after: int = Query(default=0, ge=0)) -> dict:
    """Bounded, redacted HUD events for clients using the authenticated IPC bridge."""
    response.headers["Cache-Control"] = "no-store"
    return event_hub.recent(after)


async def _stream() -> AsyncIterator[str]:
    async for event in event_hub.subscribe():
        event_type = str(event.get("type", "message"))
        payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        yield f"event: {event_type}\ndata: {payload}\n\n"


@router.get("/stream")
async def stream_events() -> StreamingResponse:
    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
        },
    )
