import asyncio
from typing import Any, Dict, Optional, Tuple

import httpx

from fastapi import APIRouter, Depends

from app.core.absolute import AkashiCore, get_core
from app.core.auth import require_api_token
from app.core.identity import AKASHI_IDENTITY
from app.core.persona import VOICE_STYLE

router = APIRouter(
    prefix="/system",
    tags=["system"],
    dependencies=[Depends(require_api_token)],
)


async def _probe_json(url: str, timeout_seconds: float = 3.0) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Probe a server-owned dependency URL without forwarding credentials."""
    try:
        async with httpx.AsyncClient(
            timeout=max(0.5, min(timeout_seconds, 3.0)),
            follow_redirects=False,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
            return True, payload if isinstance(payload, dict) else None
    except (httpx.HTTPError, ValueError):
        return False, None


async def _probe_research(core: AkashiCore) -> bool:
    """Run a minimal provider query so configured is not mistaken for reachable."""
    try:
        await asyncio.wait_for(
            core.research.provider.search("artificial intelligence", 1),
            timeout=3.0,
        )
        return True
    except Exception:
        return False


def _dependency(status: str, detail: str) -> Dict[str, str]:
    return {"status": status, "detail": detail}


@router.get("/capabilities")
async def capabilities(core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    return {
        "core": "pre-astra",
        "model_profiles": core.model_router.describe(),
        "models": core.model_router.capabilities(),
        "research_provider": core.research.provider.name,
        "features": {
            "chat": True,
            "images": True,
            "memory_v2": True,
            "research": True,
            "tools": True,
            "tasks": True,
            "files": True,
            "devices": True,
            "events": "sse",
            "live_core": True,
            "phone": core.phone.status(),
        },
        "live_actions": core.live.registry.definitions(),
    }


@router.get("/voice-persona")
async def voice_persona() -> Dict[str, str]:
    """The single source of truth for AKASHI's identity and voice register.

    Consumed by the desktop Gemini Live fast-path so its native-audio session
    speaks with the same persona as every other AKASHI surface, instead of a
    second, drifting copy of the prompt living inside the voice worker.
    """
    return {
        "name": AKASHI_IDENTITY.name,
        "identity": AKASHI_IDENTITY.render(),
        "voice_style": VOICE_STYLE,
    }


@router.get("/health")
async def dependency_health(core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    """Return a credential-safe snapshot of optional Core dependencies.

    Reaching this route proves both Core reachability and bearer authentication.
    Local Ollama and ComfyUI are probed without forwarding user credentials.
    Remote model inference is deliberately not invoked by a health check.
    """
    settings = core.settings
    ollama_url = f"{settings.ollama_base_url.rstrip('/')}/api/tags"
    comfy_url = f"{settings.comfy_base_url.rstrip('/')}/system_stats"
    (ollama_online, ollama_payload), (comfy_online, _), research_online = await asyncio.gather(
        _probe_json(ollama_url),
        _probe_json(comfy_url),
        _probe_research(core),
    )

    ollama_models = set()
    if ollama_payload:
        for item in ollama_payload.get("models", []):
            if isinstance(item, dict):
                for key in ("name", "model"):
                    value = item.get(key)
                    if isinstance(value, str):
                        ollama_models.add(value)

    quality_provider = core.model_router.describe()["quality"]
    if quality_provider == "mock":
        model = _dependency("mock", "Mock provider is active; no model inference is performed.")
    elif quality_provider == "ollama":
        model_name = settings.model_quality_name or settings.ollama_model
        if not ollama_online:
            model = _dependency("offline", "Ollama is not reachable from Core.")
        elif model_name not in ollama_models:
            model = _dependency("model_missing", "The configured Ollama model is not installed.")
        else:
            model = _dependency("online", "Configured Ollama model is available.")
    elif quality_provider == "gemini" and settings.gemini_api_key:
        model = _dependency("configured", "Gemini credential is configured; inference is not used as a health probe.")
    else:
        model = _dependency("unavailable", "The configured model provider is incomplete.")

    devices = [device for device in core.devices.list_devices() if not device.get("revoked")]
    online_devices = [device for device in devices if device.get("online")]
    return {
        "core": _dependency("online", "FastAPI Core is reachable."),
        "auth": _dependency("authorized", "Bearer access is valid."),
        "model": model,
        "ollama": _dependency(
            "online" if ollama_online else "offline",
            "Local Ollama API is reachable." if ollama_online else "Local Ollama API is not reachable.",
        ),
        "images": _dependency(
            "online" if comfy_online else "offline",
            "ComfyUI is reachable through Core." if comfy_online else "ComfyUI is not reachable from Core.",
        ),
        "research": _dependency(
            "online" if research_online else "offline",
            f"{core.research.provider.name} returned a health query."
            if research_online else f"{core.research.provider.name} did not complete a health query.",
        ),
        "desktop_agent": {
            "status": "online" if online_devices else "not_connected",
            "detail": "A paired desktop agent is online." if online_devices else "No paired desktop agent is currently online.",
            "online": len(online_devices),
            "paired": len(devices),
        },
    }
