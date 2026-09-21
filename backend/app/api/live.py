from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.absolute import AkashiCore, get_core
from app.core.auth import require_api_token


router = APIRouter(
    prefix="/live",
    tags=["live"],
    dependencies=[Depends(require_api_token)],
)


def _normalize_interaction_id(core: AkashiCore, interaction_id: str) -> str:
    try:
        return core.live.interactions.normalize_id(interaction_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/actions")
async def actions(core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    return {
        "actions": core.live.registry.definitions(),
        "discovery": core.live.registry.diagnostics(),
    }


@router.post("/interactions/{interaction_id}/cancel")
async def cancel_interaction(
    interaction_id: str,
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    normalized = _normalize_interaction_id(core, interaction_id)
    return {
        "interaction_id": normalized,
        "cancelled": await core.live.interactions.cancel(normalized),
    }


@router.get("/interactions/{interaction_id}")
async def interaction_state(
    interaction_id: str,
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    normalized = _normalize_interaction_id(core, interaction_id)
    state = await core.live.interactions.get(normalized)
    return state or {"interaction_id": normalized, "status": "not_found"}


@router.get("/interactions")
async def interaction_history(
    limit: int = Query(default=50, ge=1, le=200),
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    return {"interactions": await core.live.interactions.list(limit)}
