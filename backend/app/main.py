from fastapi import FastAPI

from app.api.chat import router as chat_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Backend foundation for Akashi AI and the ABSOLUTE Engine.",
)

app.include_router(chat_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Return a lightweight service health check."""
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "provider": settings.ai_provider,
    }
