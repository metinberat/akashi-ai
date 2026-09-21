from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.absolute import AkashiCore, get_core
from app.core.auth import require_api_token

router = APIRouter(
    prefix="/tools",
    tags=["tools"],
    dependencies=[Depends(require_api_token)],
)


class ToolInvocation(BaseModel):
    arguments: Dict[str, Any] = Field(default_factory=dict)
    approved: bool = False


@router.get("")
async def list_tools(core: AkashiCore = Depends(get_core)) -> Dict[str, List[Dict[str, Any]]]:
    return {"tools": core.tools.definitions()}


@router.post("/{tool_name}/invoke")
async def invoke_tool(
    tool_name: str,
    request: ToolInvocation,
    core: AkashiCore = Depends(get_core),
) -> Dict[str, Any]:
    try:
        return await core.tools.invoke(tool_name, request.arguments, request.approved)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
