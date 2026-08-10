from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.image import router as image_router
from app.api.chat import router as chat_router
from app.core.config import get_settings

class UTF8JSONResponse(JSONResponse):
    """JSON responses with an explicit UTF-8 charset."""

    media_type = "application/json; charset=utf-8"


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Backend foundation for Akashi AI and the ABSOLUTE Engine.",
    default_response_class=UTF8JSONResponse,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(image_router)

@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Return a lightweight service health check."""
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "provider": settings.ai_provider,
    }
