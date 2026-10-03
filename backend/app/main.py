from fastapi import FastAPI
from contextlib import asynccontextmanager

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.image import router as image_router
from app.api.intelligence import router as intelligence_router
from app.api.chat import router as chat_router
from app.api.computer import router as computer_router
from app.api.auth import router as auth_router
from app.api.autonomy import router as autonomy_router
from app.api.expertise import router as expertise_router
from app.api.character_training import router as character_training_router
from app.api.character_production import router as character_production_router
from app.api.devices import pairing_router as device_pairing_router
from app.api.devices import router as device_router
from app.api.events import router as event_router
from app.api.files import router as file_router
from app.api.memory import router as memory_router
from app.api.phone import router as phone_router
from app.api.phone import worker_router as phone_worker_router
from app.api.research import router as research_router
from app.api.system import router as system_router
from app.api.live import router as live_router
from app.api.spatial import router as spatial_router
from app.api.tasks import router as task_router
from app.api.tools import router as tool_router
from app.api.voice import router as voice_router
from app.core.absolute import get_core
from app.core.config import get_settings
from app.core.request_limits import RequestBodyLimit

class UTF8JSONResponse(JSONResponse):
    """JSON responses with an explicit UTF-8 charset."""

    media_type = "application/json; charset=utf-8"


settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    core = get_core()
    owns_runtime_state = core.scheduler.start()
    if owns_runtime_state:
        await core.live.interactions.recover_after_restart()
        core.voice_sessions.recover_after_restart()
    try:
        yield
    finally:
        await core.production_host.shutdown()
        await core.expertise.training_host.shutdown()
        core.expertise.workshop.shutdown()
        await core.autonomy.shutdown()
        if owns_runtime_state:
            core.voice_sessions.interrupt_all(
                "Backend stopped; start a fresh voice session."
            )
        await core.scheduler.stop()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Backend foundation for Akashi AI and the ABSOLUTE Engine.",
    default_response_class=UTF8JSONResponse,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Akashi-Device-Id"],
    expose_headers=["Server-Timing", "X-Akashi-Edit-Profile"],
)
app.add_middleware(RequestBodyLimit, max_bytes=settings.max_image_upload_bytes + 4 * 1024 * 1024)

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(computer_router)
app.include_router(autonomy_router)
app.include_router(expertise_router)
app.include_router(character_training_router)
app.include_router(character_production_router)
app.include_router(image_router)
app.include_router(memory_router)
app.include_router(research_router)
app.include_router(tool_router)
app.include_router(task_router)
app.include_router(file_router)
app.include_router(device_pairing_router)
app.include_router(device_router)
app.include_router(event_router)
app.include_router(system_router)
app.include_router(live_router)
app.include_router(spatial_router)
app.include_router(intelligence_router)
app.include_router(voice_router)
app.include_router(phone_router)
app.include_router(phone_worker_router)

@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Return a lightweight service health check."""
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "provider": settings.ai_provider,
    }
