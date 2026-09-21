from fastapi import APIRouter, Depends

from app.core.auth import require_api_token

router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(require_api_token)])


@router.get("/check")
async def check_access() -> dict[str, str]:
    """Lightweight authenticated probe without invoking an AI provider."""
    return {"status": "ok"}
