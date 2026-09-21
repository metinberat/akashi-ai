import secrets
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from akashi_agent.actions import ActionExecutor, action_risk
import asyncio
import subprocess
from akashi_agent.config import AgentSettings

settings = AgentSettings.from_env()
executor = ActionExecutor(settings)
app = FastAPI(
    title="AKASHI Windows Agent",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


class ActionRequest(BaseModel):
    action: str = Field(min_length=1, max_length=80)
    arguments: Dict[str, Any] = Field(default_factory=dict)
    approved: bool = False


def require_agent_token(authorization: Optional[str] = Header(default=None)) -> None:
    expected = settings.token
    if not expected or len(expected) < 32:
        raise HTTPException(status_code=503, detail="Local agent token is not configured.")
    scheme, separator, token = (authorization or "").partition(" ")
    if not separator or scheme.casefold() != "bearer" or len(token) > 512 or not secrets.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(
            status_code=401,
            detail="Invalid local agent token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "AKASHI Windows Agent",
        "bind_policy": "loopback-only",
    }


@app.get("/v1/capabilities", dependencies=[Depends(require_agent_token)])
async def capabilities() -> Dict[str, Any]:
    return {
        "actions": [
            {"name": name, "risk": action_risk(name)}
            for name in executor.capabilities()
        ],
        "applications": sorted(executor.apps),
        "allowed_roots": [str(path) for path in settings.allowed_roots],
    }


@app.post("/v1/actions/execute", dependencies=[Depends(require_agent_token)])
async def execute_action(request: ActionRequest) -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(executor.execute, request.action, request.arguments, request.approved)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (TimeoutError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=504, detail="Local action timed out.") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Local action failed.") from exc
