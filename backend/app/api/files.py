from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field

from app.core.absolute import AkashiCore, get_core
from app.core.auth import require_api_token
from app.files.service import FileRecord, FileValidationError

router = APIRouter(
    prefix="/files",
    tags=["files"],
    dependencies=[Depends(require_api_token)],
)


class FileContentResponse(BaseModel):
    file: Dict[str, Any]
    text: str


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    core: AkashiCore = Depends(get_core),
) -> FileRecord:
    try:
        content = await file.read(core.settings.max_upload_bytes + 1)
        return core.files.save(
            file.filename or "upload.txt",
            file.content_type or "text/plain",
            content,
        )
    except FileValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await file.close()


@router.get("")
async def list_files(core: AkashiCore = Depends(get_core)) -> Dict[str, List[FileRecord]]:
    return {"files": core.files.list()}


@router.get("/{file_id}")
async def get_file(file_id: str, core: AkashiCore = Depends(get_core)) -> FileRecord:
    record = core.files.get(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Uploaded file was not found.")
    return record


@router.get("/{file_id}/content", response_model=FileContentResponse)
async def get_file_content(
    file_id: str,
    max_chars: int = Query(default=50_000, ge=1, le=200_000),
    core: AkashiCore = Depends(get_core),
) -> FileContentResponse:
    record = core.files.get(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Uploaded file was not found.")
    return FileContentResponse(
        file=dict(record),
        text=core.files.get_text(file_id, max_chars=max_chars),
    )


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(file_id: str, core: AkashiCore = Depends(get_core)) -> None:
    if not core.files.delete(file_id):
        raise HTTPException(status_code=404, detail="Uploaded file was not found.")
