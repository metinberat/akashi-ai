"""Actual cached ONNX inference must reject the earlier partial artwork mask."""

import json
import sys
from pathlib import Path
from PIL import Image, ImageOps
from form_studio.shape_worker import prepare_reference, ReferenceForegroundError

with Image.open(sys.argv[1]) as image:
    image = ImageOps.exif_transpose(image).convert("RGBA")
    image.thumbnail((640, 800))
    try:
        prepare_reference(image)
    except ReferenceForegroundError:
        result = {
            "cached_foreground_model_executed": True,
            "partial_mask_rejected": True,
            "shape_generation_started": False,
            "previous_artifact_visual_acceptance": "failed",
            "next_requirement": "clean character crop or explicit alpha mask",
            "external_api_used": False,
        }
    else:
        raise AssertionError("Known partial-mask reference incorrectly accepted")
Path(__file__).resolve().parents[1].joinpath(
    ".validation/foreground-guard-report.json"
).write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result))
