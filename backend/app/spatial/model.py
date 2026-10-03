"""Spatial Lab scene document: schema constants, limits and factories.

The scene document is the single source of truth for Spatial Lab. The backend
owns it; the renderer, gesture engine, AKASHI tools and natural language all
read it and change it only through validated commands (``domain.py``).
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict

SCENE_SCHEMA = "akashi.spatial.scene/1"
DOMAIN_NAME = "akashi.spatial"
DOMAIN_VERSION = "spatial-scene-1"

OBJECT_ID = re.compile(r"^obj-[0-9a-f]{12}$")
SESSION_ID = re.compile(r"^spatial-[0-9a-f]{16}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

# Bounded interaction volume in metres. The default camera looks at the
# origin from +Z, so x is left/right, y is up and z is toward the viewer.
LIMITS: Dict[str, Any] = {
    "max_objects": 12,
    "position_min": [-4.0, -1.0, -4.0],
    "position_max": [4.0, 4.0, 2.0],
    "scale_min": 0.1,
    "scale_max": 10.0,
    "label_max": 80,
    "animation_speed_min": 0.1,
    "animation_speed_max": 3.0,
    "max_selection": 1,
}

DEFAULT_TRANSFORM: Dict[str, Any] = {"position": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0, 1.0], "scale": 1.0}


def initial_scene() -> Dict[str, Any]:
    return {
        "schema": SCENE_SCHEMA,
        "objects": {},
        "order": [],
        "selection": [],
        "view": {"hud_visible": True, "vfx_visible": True, "inspector": None},
    }


def default_transform() -> Dict[str, Any]:
    return copy.deepcopy(DEFAULT_TRANSFORM)


def new_object(object_id: str, asset: Dict[str, Any], label: str, transform: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": object_id,
        "label": label,
        "asset": copy.deepcopy(asset),
        "transform": copy.deepcopy(transform),
        "visible": True,
        "display": {"skeleton": False, "form_hud": bool(asset.get("form_hud_nodes")), "bounds": False},
        "animation": {"clip": None, "playing": False, "speed": 1.0},
    }


def object_size(obj: Dict[str, Any]) -> list:
    """Normalised bounding size at the object's current uniform scale."""
    base = obj["asset"].get("normalization", {}).get("size") or [1.0, 1.0, 1.0]
    scale = obj["transform"]["scale"]
    return [float(v) * scale for v in base]


def summarize(state: Dict[str, Any]) -> Dict[str, Any]:
    """Compact, model-safe scene description for reference resolution prompts."""
    objects = []
    for key in state["order"]:
        obj = state["objects"][key]
        asset = obj["asset"]
        form = asset.get("form") or {}
        objects.append({
            "id": key,
            "label": obj["label"],
            "selected": key in state["selection"],
            "visible": obj["visible"],
            "position": obj["transform"]["position"],
            "scale": obj["transform"]["scale"],
            "source": asset.get("source"),
            "form_project": form.get("project_name"),
            "form_version": form.get("version_index"),
            "clips": [clip["name"] for clip in asset.get("clips", [])][:12],
            "rigged": bool(asset.get("joints")),
            "form_hud": bool(asset.get("form_hud_nodes")),
        })
    return {"objects": objects, "view": dict(state["view"])}
