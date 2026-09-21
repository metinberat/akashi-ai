import asyncio
import json
import logging
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Literal, Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from fastapi.responses import Response
from app.core.auth import require_api_token
from app.core.config import get_settings


router = APIRouter(prefix="/image", tags=["image"], dependencies=[Depends(require_api_token)])

settings = get_settings()
logger = logging.getLogger(__name__)
COMFY_BASE_URL = settings.comfy_base_url
WORKFLOW_PATH = (
    Path(__file__).resolve().parents[2] / "workflows" / "z_image_fast_api.json"
)
QWEN_WORKFLOW_PATH = (
    Path(__file__).resolve().parents[2] / "workflows" / "qwen_quality_api.json"
)
EDIT_WORKFLOW_PATH = (
    Path(__file__).resolve().parents[2] / "workflows" / "qwen_edit_api.json"
)

class ImageRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)


class ImageTestResponse(BaseModel):
    prompt_id: str
    images: list[str]


EditProfile = Literal["fast", "quality"]
EditStage = Literal["preparing", "editing", "finalizing", "completed", "failed"]


class EditProgressResponse(BaseModel):
    stage: EditStage
    profile: EditProfile


_edit_progress: Dict[str, Dict[str, Any]] = {}
_EDIT_PROGRESS_TTL_SECONDS = 15 * 60


def _normalize_request_id(request_id: Optional[str]) -> Optional[str]:
    if not request_id:
        return None
    try:
        return str(uuid.UUID(request_id))
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid edit request identifier.") from exc


def _set_edit_progress(
    request_id: Optional[str], stage: EditStage, profile: EditProfile
) -> None:
    if request_id is None:
        return
    now = time.monotonic()
    expired = [
        key for key, value in _edit_progress.items()
        if now - float(value["updated_at"]) > _EDIT_PROGRESS_TTL_SECONDS
    ]
    for key in expired:
        _edit_progress.pop(key, None)
    _edit_progress[request_id] = {
        "stage": stage,
        "profile": profile,
        "updated_at": now,
    }


def configure_edit_workflow(
    workflow: Dict[str, Any], image_name: str, prompt: str, profile: EditProfile
) -> None:
    """Apply one genuine workflow profile without changing the public response contract."""
    workflow["41"]["inputs"]["image"] = image_name
    workflow["170:151"]["inputs"]["prompt"] = prompt.strip()
    # The 19 GiB edit UNet and 8.7 GiB text encoder cannot coexist in 16 GiB
    # VRAM. Keeping text encoding on CPU avoids an unstable GPU swap between
    # consecutive requests while diffusion and VAE work remain GPU accelerated.
    workflow["170:162"]["inputs"]["device"] = "cpu"
    workflow["170:168"]["inputs"]["value"] = profile == "fast"
    if profile == "fast":
        # The supplied Lightning path is trained for four steps, but eight gives
        # the edit latent enough refinement to avoid frequent block artifacts while
        # remaining far below the 40-step fidelity path.
        workflow["170:165"]["inputs"]["value"] = 8
    workflow["170:169"]["inputs"]["seed"] = uuid.uuid4().int % (2**63 - 1)


def _comfy_execution_timings(
    history_entry: Dict[str, Any], submitted_epoch_ms: float
) -> Dict[str, float]:
    timestamps: Dict[str, float] = {}
    messages = history_entry.get("status", {}).get("messages", [])
    for message in messages:
        if not isinstance(message, list) or len(message) != 2 or not isinstance(message[1], dict):
            continue
        timestamp = message[1].get("timestamp")
        if message[0] in {"execution_start", "execution_success"} and isinstance(timestamp, (int, float)):
            timestamps[message[0]] = float(timestamp)
    result: Dict[str, float] = {}
    started = timestamps.get("execution_start")
    completed = timestamps.get("execution_success")
    if started is not None:
        result["comfy_queue"] = max(0.0, started - submitted_epoch_ms)
    if started is not None and completed is not None:
        result["comfy_execute"] = max(0.0, completed - started)
    return result


def _server_timing(timings: Dict[str, float]) -> str:
    return ", ".join(f"{name};dur={duration:.1f}" for name, duration in timings.items())


def validate_image_location(filename: str, subfolder: str) -> None:
    if not filename or Path(filename).name != filename or any(
        character in filename for character in ("/", "\\", "\x00", ":")
    ):
        raise ValueError("Invalid image filename.")
    if Path(filename).suffix.casefold() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        raise ValueError("Only generated image files can be retrieved.")
    normalized_subfolder = PurePosixPath(subfolder.replace("\\", "/"))
    if normalized_subfolder.is_absolute() or ".." in normalized_subfolder.parts or any(char in subfolder for char in (":", "\x00")):
        raise ValueError("Invalid image subfolder.")


def extract_image_urls(history_entry: dict) -> list[str]:
    image_urls: list[str] = []
    outputs = history_entry.get("outputs", {})

    for node_output in outputs.values():
        for image in node_output.get("images", []):
            try:
                filename = image["filename"]
                subfolder = image.get("subfolder", "")
                image_type = image.get("type", "output")
                validate_image_location(filename, subfolder)
                if image_type not in {"input", "output", "temp"}:
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            query = urlencode(
                {
                    "filename": filename,
                    "subfolder": subfolder,
                    "type": image_type,
                }
            )
            image_urls.append(f"/image/view?{query}")

    return image_urls


async def _comfy_request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    require_success: bool = True,
    **kwargs: Any,
) -> httpx.Response:
    try:
        response = await client.request(method, f"{COMFY_BASE_URL}{path}", **kwargs)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="ComfyUI is not reachable from Core.") from exc
    if require_success and not response.is_success:
        raise HTTPException(
            status_code=502,
            detail=f"ComfyUI rejected the request ({response.status_code}).",
        )
    return response

@router.get("/view")
async def view_image(
    filename: str,
    subfolder: str = "",
    type: Literal["input", "output", "temp"] = "output",
) -> Response:
    try:
        validate_image_location(filename, subfolder)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await _comfy_request(
            client,
            "GET",
            "/view",
            require_success=False,
            params={
                "filename": filename,
                "subfolder": subfolder,
                "type": type,
            },
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail="ComfyUI image could not be loaded.",
        )

    if not response.headers.get("content-type", "").startswith("image/"):
        raise HTTPException(status_code=502, detail="Image backend returned a non-image response.")
    return Response(
        content=response.content,
        media_type=response.headers.get("content-type", "image/png"),
        headers={
            "Cache-Control": "private, no-store",
            "Server-Timing": _server_timing({"comfy_result": (time.perf_counter() - started) * 1000}),
        },
    )


@router.get("/edit/status/{request_id}", response_model=EditProgressResponse)
async def edit_status(request_id: str) -> EditProgressResponse:
    normalized = _normalize_request_id(request_id)
    progress = _edit_progress.get(normalized or "")
    if progress is None or time.monotonic() - float(progress["updated_at"]) > _EDIT_PROGRESS_TTL_SECONDS:
        raise HTTPException(status_code=404, detail="Edit progress is not available.")
    return EditProgressResponse(stage=progress["stage"], profile=progress["profile"])

@router.post("/fast-test", response_model=ImageTestResponse)
async def fast_test_image(request: ImageRequest) -> ImageTestResponse:
    if not WORKFLOW_PATH.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Workflow file not found: {WORKFLOW_PATH}",
        )

    with WORKFLOW_PATH.open("r", encoding="utf-8") as f:
        workflow = json.load(f)

    workflow["57:27"]["inputs"]["text"] = request.prompt

    client_id = str(uuid.uuid4())

    async with httpx.AsyncClient(timeout=300.0) as client:
        queue_response = await _comfy_request(
            client,
            "POST",
            "/prompt",
            json={
                "prompt": workflow,
                "client_id": client_id,
            },
        )
        prompt_id = queue_response.json()["prompt_id"]

        for _ in range(300):
            history_response = await _comfy_request(
                client,
                "GET",
                f"/history/{prompt_id}",
            )
            history_data = history_response.json()

            if prompt_id in history_data:
                image_urls = extract_image_urls(history_data[prompt_id])

                if not image_urls:
                    raise HTTPException(
                        status_code=502,
                        detail="Fast generation completed but no image was returned.",
                    )

                return ImageTestResponse(
                    prompt_id=prompt_id,
                    images=image_urls,
                )

            await asyncio.sleep(1)

    raise HTTPException(
        status_code=504,
        detail="Timed out while waiting for fast image generation.",
    )

@router.post("/quality-test", response_model=ImageTestResponse)
async def quality_test_image(request: ImageRequest) -> ImageTestResponse:
    if not QWEN_WORKFLOW_PATH.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Workflow file not found: {QWEN_WORKFLOW_PATH}",
        )

    with QWEN_WORKFLOW_PATH.open("r", encoding="utf-8") as f:
        workflow = json.load(f)

    workflow["238:227"]["inputs"]["text"] = (
    request.prompt
    + ", photorealistic real-world photography, natural camera exposure, "
    + "realistic materials and reflections, subtle sensor noise, natural depth of field, "
    + "slight real-world imperfections, physically accurate lighting, realistic textures, "
    + "documentary photography, no CGI look, no 3D render, no anime, no illustration"
    )
    workflow["238:230"]["inputs"]["seed"] = uuid.uuid4().int % (2**63 - 1)

    workflow["238:228"]["inputs"]["text"] += (
    ", CGI, 3D render, anime, illustration, cartoon, plastic surface, "
    "overly smooth, artificial reflections, oversaturated, fake lighting"
    )

    client_id = str(uuid.uuid4())

    async with httpx.AsyncClient(timeout=300.0) as client:
        queue_response = await _comfy_request(
            client,
            "POST",
            "/prompt",
            json={
                "prompt": workflow,
                "client_id": client_id,
            },
        )
        queue_data = queue_response.json()
        prompt_id = queue_data["prompt_id"]

        for _ in range(300):
            history_response = await _comfy_request(
                client,
                "GET",
                f"/history/{prompt_id}",
            )
            history_data = history_response.json()

            if prompt_id in history_data:
                image_urls = extract_image_urls(history_data[prompt_id])

                if not image_urls:
                    raise HTTPException(
                        status_code=502,
                        detail="Workflow completed but no images were returned.",
                    )

                return ImageTestResponse(
                    prompt_id=prompt_id,
                    images=image_urls,
                )

            await asyncio.sleep(1)

    raise HTTPException(
        status_code=504,
        detail="Timed out while waiting for ComfyUI image generation.",
    )


@router.post("/edit", response_model=ImageTestResponse)
async def edit_image(
    response: Response,
    prompt: str = Form(..., min_length=1, max_length=20_000),
    image: UploadFile = File(...),
    profile: EditProfile = Form("quality"),
    request_id: Optional[str] = Form(None),
) -> ImageTestResponse:
    normalized_request_id = _normalize_request_id(request_id)
    _set_edit_progress(normalized_request_id, "preparing", profile)
    total_started = time.perf_counter()
    timings: Dict[str, float] = {}
    try:
        prepare_started = time.perf_counter()
        if not EDIT_WORKFLOW_PATH.exists():
            raise HTTPException(
                status_code=500,
                detail=f"Workflow file not found: {EDIT_WORKFLOW_PATH}",
            )

        with EDIT_WORKFLOW_PATH.open("r", encoding="utf-8") as f:
            workflow = json.load(f)

        image_bytes = await image.read(settings.max_image_upload_bytes + 1)

        if not (image.content_type or "").startswith("image/"):
            raise HTTPException(status_code=422, detail="EDIT accepts image uploads only.")
        if len(image_bytes) > settings.max_image_upload_bytes:
            raise HTTPException(status_code=413, detail="Uploaded image is too large.")
        if not image_bytes:
            raise HTTPException(status_code=422, detail="Uploaded image is empty.")
        if not (image_bytes.startswith(b"\x89PNG\r\n\x1a\n") or image_bytes.startswith(b"\xff\xd8\xff") or (image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP")):
            raise HTTPException(status_code=422, detail="Upload is not a recognized PNG, JPEG or WebP image.")

        suffix = Path(image.filename or "image.png").suffix.casefold() or ".png"
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise HTTPException(status_code=422, detail="Unsupported image extension.")
        comfy_filename = f"akashi_edit_{uuid.uuid4().hex}{suffix}"
        timings["prepare"] = (time.perf_counter() - prepare_started) * 1000

        async with httpx.AsyncClient(timeout=300.0) as client:
            upload_started = time.perf_counter()
            upload_response = await _comfy_request(
                client,
                "POST",
                "/upload/image",
                files={
                    "image": (
                        comfy_filename,
                        image_bytes,
                        image.content_type or "application/octet-stream",
                    )
                },
                data={
                    "type": "input",
                    "overwrite": "true",
                },
            )
            timings["comfy_upload"] = (time.perf_counter() - upload_started) * 1000
            upload_data = upload_response.json()

            uploaded_name = upload_data["name"]
            uploaded_subfolder = upload_data.get("subfolder", "")
            workflow_image_name = (
                f"{uploaded_subfolder}/{uploaded_name}"
                if uploaded_subfolder else uploaded_name
            )
            configure_edit_workflow(workflow, workflow_image_name, prompt, profile)

            queue_started = time.perf_counter()
            submitted_epoch_ms = time.time() * 1000
            queue_response = await _comfy_request(
                client,
                "POST",
                "/prompt",
                json={
                    "prompt": workflow,
                    "client_id": str(uuid.uuid4()),
                },
            )
            timings["queue_submit"] = (time.perf_counter() - queue_started) * 1000
            prompt_id = queue_response.json()["prompt_id"]
            _set_edit_progress(normalized_request_id, "editing", profile)

            for _ in range(1200):
                history_response = await _comfy_request(
                    client,
                    "GET",
                    f"/history/{prompt_id}",
                )
                history_data = history_response.json()

                if prompt_id in history_data:
                    _set_edit_progress(normalized_request_id, "finalizing", profile)
                    history_entry = history_data[prompt_id]
                    timings.update(_comfy_execution_timings(history_entry, submitted_epoch_ms))
                    image_urls = extract_image_urls(history_entry)

                    if not image_urls:
                        raise HTTPException(
                            status_code=502,
                            detail="Edit completed but no image was returned.",
                        )

                    timings["api_total"] = (time.perf_counter() - total_started) * 1000
                    response.headers["Server-Timing"] = _server_timing(timings)
                    response.headers["X-Akashi-Edit-Profile"] = profile
                    logger.info(
                        "image_edit_complete profile=%s prompt_id=%s timings_ms=%s",
                        profile,
                        prompt_id,
                        {name: round(value, 1) for name, value in timings.items()},
                    )
                    _set_edit_progress(normalized_request_id, "completed", profile)
                    return ImageTestResponse(prompt_id=prompt_id, images=image_urls)

                await asyncio.sleep(0.25)

        raise HTTPException(
            status_code=504,
            detail="Timed out while waiting for ComfyUI image edit.",
        )
    except Exception:
        _set_edit_progress(normalized_request_id, "failed", profile)
        raise
