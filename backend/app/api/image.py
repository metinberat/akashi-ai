import asyncio
import json
import uuid
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


router = APIRouter(prefix="/image", tags=["image"])

COMFY_BASE_URL = "http://127.0.0.1:8188"
WORKFLOW_PATH = (
    Path(__file__).resolve().parents[2] / "workflows" / "z_image_fast_api.json"
)
QWEN_WORKFLOW_PATH = (
    Path(__file__).resolve().parents[2] / "workflows" / "qwen_quality_api.json"
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