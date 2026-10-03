"""Pure, deterministic Spatial Lab reducer.

Input commands are *concrete*: references are already resolved to object ids,
relative transforms are already absolute and assets are already inspected
summaries (see ``compiler.py``). This keeps the reducer free of I/O, clocks and
randomness so every session can be replayed exactly.
"""

from __future__ import annotations

import math
from typing import Any, Dict

from app.history.engine import CommandRejected, DomainResult
from app.spatial.geometry import canonical_quat, finite, q3
from app.spatial.model import DOMAIN_NAME, DOMAIN_VERSION, LIMITS, OBJECT_ID, SHA256
from app.history.canonical import quantize

DISPLAY_FLAGS = ("skeleton", "form_hud", "bounds")
VIEW_FLAGS = ("hud_visible", "vfx_visible")


def reject(code: str, message: str, **details: Any) -> CommandRejected:
    return CommandRejected(code, message, details)


def _object(state: Dict[str, Any], object_id: Any) -> Dict[str, Any]:
    if not isinstance(object_id, str) or object_id not in state["objects"]:
        raise reject("object_not_found", "The target object is not in this scene.", object_id=object_id)
    return state["objects"][object_id]


def _bool(command: Dict[str, Any], key: str) -> bool:
    value = command.get(key)
    if type(value) is not bool:
        raise reject("invalid_field", f"{key} must be true or false.")
    return value


def validate_transform(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"position", "rotation", "scale"}:
        raise reject("invalid_transform", "Transform needs exactly position, rotation and scale.")
    position, rotation, scale = value["position"], value["rotation"], value["scale"]
    if not isinstance(position, list) or len(position) != 3 or not finite(position):
        raise reject("invalid_transform", "Position must be three finite numbers.")
    if not isinstance(rotation, list) or len(rotation) != 4 or not finite(rotation):
        raise reject("invalid_transform", "Rotation must be a finite [x, y, z, w] quaternion.")
    if not finite([scale]):
        raise reject("invalid_transform", "Scale must be a finite number.")
    length = math.sqrt(sum(float(v) * float(v) for v in rotation))
    if not 0.98 <= length <= 1.02:
        raise reject("invalid_transform", "Rotation quaternion must be unit length.")
    low, high = LIMITS["position_min"], LIMITS["position_max"]
    for axis, (component, lo, hi) in enumerate(zip(position, low, high)):
        if not lo <= component <= hi:
            raise reject("out_of_bounds", f"Position {'xyz'[axis]}={component:.3f} is outside the workspace [{lo}, {hi}].",
                         axis="xyz"[axis], value=component, minimum=lo, maximum=hi)
    if not LIMITS["scale_min"] <= scale <= LIMITS["scale_max"]:
        raise reject("out_of_bounds", f"Scale {scale:.3f} is outside [{LIMITS['scale_min']}, {LIMITS['scale_max']}].",
                     axis="scale", value=scale, minimum=LIMITS["scale_min"], maximum=LIMITS["scale_max"])
    return {"position": q3(position), "rotation": canonical_quat(rotation), "scale": quantize(float(scale))}


def validate_asset(asset: Any) -> Dict[str, Any]:
    if not isinstance(asset, dict):
        raise reject("invalid_asset", "Asset summary is required.")
    if not isinstance(asset.get("asset_id"), str) or not SHA256.match(asset["asset_id"]):
        raise reject("invalid_asset", "Asset identity must be its SHA-256 digest.")
    if asset.get("format") != "glb" or asset.get("source") not in {"form", "upload", "fixture"}:
        raise reject("invalid_asset", "Only inspected GLB assets from FORM, uploads or fixtures are supported.")
    clips = asset.get("clips")
    if not isinstance(clips, list) or any(not isinstance(c, dict) or not isinstance(c.get("name"), str) for c in clips):
        raise reject("invalid_asset", "Asset clip list is malformed.")
    normalization = asset.get("normalization")
    if not isinstance(normalization, dict) or not finite([normalization.get("scale", float("nan"))]):
        raise reject("invalid_asset", "Asset normalization is missing.")
    return asset


def _label(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > LIMITS["label_max"]:
        raise reject("invalid_label", f"Label must be 1-{LIMITS['label_max']} characters.")
    return value.strip()


class SpatialSceneDomain:
    name = DOMAIN_NAME
    version = DOMAIN_VERSION

    def apply(self, state: Dict[str, Any], command: Dict[str, Any]) -> DomainResult:
        kind = command.get("type")
        handler = getattr(self, "_" + str(kind).replace(".", "_"), None)
        if handler is None or not isinstance(kind, str):
            raise reject("unknown_command", f"Unknown scene command {kind!r}.")
        return handler(state, command)

    def reconcile(self, state: Dict[str, Any]) -> Dict[str, Any]:
        objects = state["objects"]
        state["order"] = [key for key in state["order"] if key in objects]
        state["selection"] = [key for key in state["selection"] if key in objects]
        if state["view"].get("inspector") not in objects:
            state["view"]["inspector"] = None
        return state

    # Scene membership ------------------------------------------------------------
    def _object_add(self, state, command):
        obj = command.get("object")
        if not isinstance(obj, dict) or not isinstance(obj.get("id"), str) or not OBJECT_ID.match(obj["id"]):
            raise reject("invalid_object", "Object id must look like obj-<12 hex>.")
        if obj["id"] in state["objects"]:
            raise reject("duplicate_object", "Object id already exists.")
        if len(state["objects"]) >= LIMITS["max_objects"]:
            raise reject("scene_full", f"Spatial Lab V1 holds at most {LIMITS['max_objects']} objects.")
        asset = validate_asset(obj.get("asset"))
        clean = {
            "id": obj["id"],
            "label": _label(obj.get("label")),
            "asset": asset,
            "transform": validate_transform(obj.get("transform")),
            "visible": True,
            "display": {"skeleton": False, "form_hud": bool(asset.get("form_hud_nodes")), "bounds": False},
            "animation": {"clip": None, "playing": False, "speed": 1.0},
        }
        state["objects"][clean["id"]] = clean
        state["order"].append(clean["id"])
        return DomainResult(state, "scene", True, [clean["id"]], f"Added {clean['label']}")

    def _object_remove(self, state, command):
        obj = _object(state, command.get("object_id"))
        del state["objects"][obj["id"]]
        self.reconcile(state)
        return DomainResult(state, "scene", True, [obj["id"]], f"Removed {obj['label']}")

    # Selection / inspection (recorded, not undoable) ------------------------------
    def _selection_set(self, state, command):
        ids = command.get("object_ids")
        if not isinstance(ids, list) or len(ids) > LIMITS["max_selection"] or len(set(ids)) != len(ids):
            raise reject("invalid_selection", f"Select at most {LIMITS['max_selection']} distinct object(s).")
        for key in ids:
            _object(state, key)
        state["selection"] = list(ids)
        return DomainResult(state, "selection", False, list(ids), "Selected " + (", ".join(state["objects"][k]["label"] for k in ids) or "nothing"))

    def _view_inspect(self, state, command):
        target = command.get("object_id")
        if target is not None:
            _object(state, target)
        state["view"]["inspector"] = target
        return DomainResult(state, "selection", False, [target] if target else [], "Inspector " + (state["objects"][target]["label"] if target else "closed"))

    # Object properties -----------------------------------------------------------
    def _object_transform(self, state, command):
        obj = _object(state, command.get("object_id"))
        obj["transform"] = validate_transform(command.get("transform"))
        return DomainResult(state, "transform", True, [obj["id"]], f"Transformed {obj['label']}")

    def _object_visibility(self, state, command):
        obj = _object(state, command.get("object_id"))
        obj["visible"] = _bool(command, "visible")
        return DomainResult(state, "display", True, [obj["id"]], ("Showed " if obj["visible"] else "Hid ") + obj["label"])

    def _object_display(self, state, command):
        obj = _object(state, command.get("object_id"))
        changes = {key: command[key] for key in DISPLAY_FLAGS if key in command}
        if not changes or set(command) - set(DISPLAY_FLAGS) - {"type", "object_id"}:
            raise reject("invalid_field", "Display accepts skeleton, form_hud and bounds flags.")
        for key in changes:
            _bool(command, key)
        if changes.get("skeleton") and not obj["asset"].get("joints"):
            raise reject("no_rig", f"{obj['label']} has no skeleton to show.")
        if changes.get("form_hud") and not obj["asset"].get("form_hud_nodes"):
            raise reject("no_form_hud", f"{obj['label']} has no FORM HUD geometry.")
        obj["display"].update(changes)
        return DomainResult(state, "display", True, [obj["id"]], f"Display changed for {obj['label']}")

    def _object_animation(self, state, command):
        obj = _object(state, command.get("object_id"))
        clip = command.get("clip")
        playing = _bool(command, "playing")
        speed = command.get("speed", obj["animation"]["speed"])
        names = [c["name"] for c in obj["asset"].get("clips", [])]
        if clip is not None and clip not in names:
            raise reject("clip_not_found", f"{obj['label']} has no clip named {clip!r}.", available=names)
        if clip is None and playing:
            raise reject("clip_required", "Choose a clip before playing.", available=names)
        if not finite([speed]) or not LIMITS["animation_speed_min"] <= speed <= LIMITS["animation_speed_max"]:
            raise reject("invalid_speed", "Animation speed is outside the supported range.")
        obj["animation"] = {"clip": clip, "playing": playing, "speed": quantize(float(speed), 3)}
        return DomainResult(state, "animation", True, [obj["id"]],
                            (f"Playing {clip}" if playing else f"Paused {clip}" if clip else "Stopped animation") + f" on {obj['label']}")

    def _object_asset(self, state, command):
        obj = _object(state, command.get("object_id"))
        asset = validate_asset(command.get("asset"))
        obj["asset"] = asset
        if "label" in command:
            obj["label"] = _label(command["label"])
        names = {c["name"] for c in asset.get("clips", [])}
        if obj["animation"]["clip"] not in names:
            obj["animation"] = {"clip": None, "playing": False, "speed": obj["animation"]["speed"]}
        if not asset.get("joints"):
            obj["display"]["skeleton"] = False
        if not asset.get("form_hud_nodes"):
            obj["display"]["form_hud"] = False
        return DomainResult(state, "asset", True, [obj["id"]], f"Switched {obj['label']} asset version")

    def _object_rename(self, state, command):
        obj = _object(state, command.get("object_id"))
        obj["label"] = _label(command.get("label"))
        return DomainResult(state, "scene", True, [obj["id"]], f"Renamed to {obj['label']}")

    def _view_set(self, state, command):
        changes = {key: command[key] for key in VIEW_FLAGS if key in command}
        if not changes or set(command) - set(VIEW_FLAGS) - {"type"}:
            raise reject("invalid_field", "View accepts hud_visible and vfx_visible.")
        for key in changes:
            _bool(command, key)
        state["view"].update(changes)
        return DomainResult(state, "view", True, [], "View: " + ", ".join(f"{k}={v}" for k, v in sorted(changes.items())))
