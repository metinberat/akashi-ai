from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.absolute import AkashiCore, get_core
from app.core.auth import require_api_token
from app.core.model_router import ModelProfile
from app.core.router import ProviderConfigurationError
from app.live.core import InteractionCancelled
from app.providers.images import decode_image

router = APIRouter(prefix="/chat", tags=["chat"], dependencies=[Depends(require_api_token)])

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    session_id: str = Field(default="default", min_length=1, max_length=128)
    mode: Literal["private", "public"] = "private"
    model_profile: ModelProfile = "quality"
    file_ids: List[str] = Field(default_factory=list, max_length=5)
    voice: bool = False
    images: List[str] = Field(default_factory=list, max_length=1)
    interaction_id: Optional[str] = Field(default=None, min_length=8, max_length=128)


class ChatResponse(BaseModel):
    response: str
    session_id: str
    provider: str
    mode: Literal["private", "public"]
    intent: Literal["study", "code", "research", "casual", "planning", "unknown"]


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    core: AkashiCore = Depends(get_core),
) -> ChatResponse:
    """Send a message through the configured ABSOLUTE Engine provider."""
    try:
        if not request.message.strip():
            raise ValueError("Message cannot be blank.")
        if request.images and request.model_profile != "vision":
            raise ValueError("Select VISION to analyze an image.")
        for image in request.images:
            decode_image(image)
        result = await core.chat(
            message=request.message,
            session_id=request.session_id,
            mode=request.mode,
            profile=request.model_profile,
            file_ids=request.file_ids,
            voice=request.voice,
            images=request.images,
            interaction_id=request.interaction_id,
        )
    except ProviderConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except InteractionCancelled as exc:
        raise HTTPException(status_code=409, detail="Interaction cancelled.") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="The configured AI provider could not complete the request.",
        ) from exc

    return ChatResponse(
        response=result.text,
        session_id=result.session_id,
        provider=result.provider,
        mode=request.mode,
        intent=result.intent,
    )
