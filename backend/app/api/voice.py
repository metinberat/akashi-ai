from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.core.absolute import AkashiCore, get_core
from app.core.auth import require_api_token


router = APIRouter(
    prefix="/voice/sessions",
    tags=["voice"],
    dependencies=[Depends(require_api_token)],
)


class StartVoiceSession(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    language: Literal["auto", "tr", "en"] = "auto"


class VoiceTransition(BaseModel):
    state: Literal["idle", "listening", "transcribing", "thinking", "acting", "speaking", "interrupted", "error"]
    interaction_id: Optional[str] = Field(default=None, max_length=128)
    last_user_utterance: Optional[str] = Field(default=None, max_length=2_000)
    last_assistant_utterance: Optional[str] = Field(default=None, max_length=2_000)
    error: Optional[str] = Field(default=None, max_length=500)


@router.post("")
async def start(
    request: StartVoiceSession,
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    return core.voice_sessions.start(request.session_id, request.language)


@router.get("/{voice_session_id}")
async def get_session(
    voice_session_id: str,
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    item = core.voice_sessions.get(voice_session_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Voice session was not found.")
    return item


@router.patch("/{voice_session_id}")
async def transition(
    voice_session_id: str,
    request: VoiceTransition,
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    try:
        return core.voice_sessions.transition(
            voice_session_id,
            request.state,
            request.interaction_id,
            request.last_user_utterance,
            request.last_assistant_utterance,
            request.error,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{voice_session_id}/interrupt")
async def interrupt(
    voice_session_id: str,
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    try:
        return core.voice_sessions.interrupt(voice_session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{voice_session_id}", status_code=204)
async def stop(
    voice_session_id: str,
    core: AkashiCore = Depends(get_core),
) -> Response:
    core.voice_sessions.stop(voice_session_id)
    return Response(status_code=204)

