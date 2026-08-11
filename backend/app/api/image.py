import asyncio
import json
import uuid
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel


router = APIRouter(prefix="/image", tags=["image"])

COMFY_BASE_URL = "http://127.0.0.1:8188"
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
    prompt: str


class ImageTestResponse(BaseModel):
    prompt_id: str
    images: list[str]


def extract_image_urls(history_entry: dict) -> list[str]:
    image_urls: list[str] = []
    outputs = history_entry.get("outputs", {})

    for node_output in outputs.values():
        for image in node_output.get("images", []):
            query = urlencode(
                {
                    "filename": image["filename"],
                    "subfolder": image.get("subfolder", ""),
                    "type": image.get("type", "output"),
                }
            )
            image_urls.append(f"{COMFY_BASE_URL}/view?{query}")

    return image_urls


@router.post("/quality-test", response_model=ImageTestResponse)
async def quality_test_image(request: ImageRequest) -> ImageTestResponse:
    if not QWEN_WORKFLOW_PATH.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Workflow file not found: {QWEN_WORKFLOW_PATH}",
        )

    with QWEN_WORKFLOW_PATH.open("r", encoding="utf-8") as f:
        workflow = json.load(f)
    
    workflow["238:227"]["inputs"]["text"] = request.prompt

    client_id = str(uuid.uuid4())

    async with httpx.AsyncClient(timeout=300.0) as client:
        queue_response = await client.post(
            f"{COMFY_BASE_URL}/prompt",
            json={
                "prompt": workflow,
                "client_id": client_id,
            },
        )
        queue_response.raise_for_status()
        queue_data = queue_response.json()
        prompt_id = queue_data["prompt_id"]

        for _ in range(300):
            history_response = await client.get(
                f"{COMFY_BASE_URL}/history/{prompt_id}"
            )
            history_response.raise_for_status()
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
    prompt: str = Form(...),
    image: UploadFile = File(...),
) -> ImageTestResponse:
    if not EDIT_WORKFLOW_PATH.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Workflow file not found: {EDIT_WORKFLOW_PATH}",
        )

    with EDIT_WORKFLOW_PATH.open("r", encoding="utf-8") as f:
        workflow = json.load(f)

    image_bytes = await image.read()

    suffix = Path(image.filename or "image.png").suffix or ".png"
    comfy_filename = f"akashi_edit_{uuid.uuid4().hex}{suffix}"

    async with httpx.AsyncClient(timeout=300.0) as client:
        upload_response = await client.post(
            f"{COMFY_BASE_URL}/upload/image",
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
        upload_response.raise_for_status()
        upload_data = upload_response.json()

        uploaded_name = upload_data["name"]
        uploaded_subfolder = upload_data.get("subfolder", "")

        if uploaded_subfolder:
            workflow_image_name = f"{uploaded_subfolder}/{uploaded_name}"
        else:
            workflow_image_name = uploaded_name

        workflow["41"]["inputs"]["image"] = workflow_image_name
        workflow["170:151"]["inputs"]["prompt"] = prompt

        client_id = str(uuid.uuid4())

        queue_response = await client.post(
            f"{COMFY_BASE_URL}/prompt",
            json={
                "prompt": workflow,
                "client_id": client_id,
            },
        )
        queue_response.raise_for_status()

        prompt_id = queue_response.json()["prompt_id"]

        for _ in range(300):
            history_response = await client.get(
                f"{COMFY_BASE_URL}/history/{prompt_id}"
            )
            history_response.raise_for_status()
            history_data = history_response.json()

            if prompt_id in history_data:
                image_urls = extract_image_urls(history_data[prompt_id])

                if not image_urls:
                    raise HTTPException(
                        status_code=502,
                        detail="Edit completed but no image was returned.",
                    )

                return ImageTestResponse(
                    prompt_id=prompt_id,
                    images=image_urls,
                )

            await asyncio.sleep(1)

    raise HTTPException(
        status_code=504,
        detail="Timed out while waiting for ComfyUI image edit.",
    )