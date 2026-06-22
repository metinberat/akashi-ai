from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.brain import AkashiBrain
from app.core.config import get_settings
from app.core.router import ProviderConfigurationError, create_provider
from app.memory.json_memory import JSONMemory

router = APIRouter(prefix="/chat", tags=["chat"])

settings = get_settings()
brain = AkashiBrain(
    provider=create_provider(settings),
    memory=JSONMemory(settings.memory_file),
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    session_id: str = Field(default="default", min_length=1, max_length=128)
    mode: Literal["private", "public"] = "private"


class ChatResponse(BaseModel):
    response: str
    session_id: str
    provider: str
    mode: Literal["private", "public"]
    intent: Literal["study", "code", "research", "casual", "planning", "unknown"]


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Send a message through the configured ABSOLUTE Engine provider."""
    try:
        result = await brain.respond(
            message=request.message,
            session_id=request.session_id,
            mode=request.mode,
        )
    except ProviderConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
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
