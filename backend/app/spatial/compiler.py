"""Compile public requests into concrete, deterministic scene commands.

This is where references are resolved, relative operations ("bigger", "rotate
180 degrees", "to my right hand") become absolute transforms, assets are
resolved through the registry/FORM, and clip names are matched. The reducer then
validates and applies the concrete commands; replay re-executes those exact
commands without consulting the registry, FORM, the camera or a model again.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from app.history.canonical import quantize
from app.history.engine import CommandRejected
from app.live.actions.base import normalize_text
from app.spatial import requests as rq
from app.spatial.assets import AssetError, AssetRegistry
from app.spatial.form_library import FormLibraryError
from app.spatial.geometry import q3, rotate_world
from app.spatial.model import LIMITS, default_transform, new_object, object_size
from app.spatial.references import Clarification, resolve

CLIP_CONCEPTS = {
    "walk": ("walk", "yuru", "yuruyus", "yurume"),
    "run": ("run", "jog", "kos", "kosu", "kosma"),
    "idle": ("idle", "bekle", "bekleme", "rest"),
    "wave": ("wave", "salla", "selam"),
    "dance": ("dance", "dans"),
    "jump": ("jump", "zipla"),
    "sway": ("sway", "salin"),
    "breath": ("breath", "breathe", "nefes"),
}
VERSION_LABEL = re.compile(r"^v?0*(\d{1,3})$", re.IGNORECASE)


@dataclass
class Prepared:
    request: Dict[str, Any]
    commands: List[Dict[str, Any]] = field(default_factory=list)
    history: Optional[str] = None
    risk: str = "safe"
    targets: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    lease_id: Optional[str] = None


@dataclass
class CompileContext:
    state: Dict[str, Any]
    events: Sequence[Dict[str, Any]]
    assets: AssetRegistry
    anchors: Dict[str, Any] = field(default_factory=dict)
    new_id: Callable[[], str] = lambda: "obj-" + uuid.uuid4().hex[:12]


def match_clip(query: str, clips: Sequence[Dict[str, Any]], label: str) -> str:
    names = [c["name"] for c in clips]
    if not names:
        raise CommandRejected("no_clips", f"{label} has no animation clips.", {"available": []})
    wanted = normalize_text(query)
    exact = [n for n in names if normalize_text(n) == wanted]
    if exact:
        return exact[0]
    tokens = set(re.findall(r"[a-z0-9]+", wanted))
    concepts = [words for words in CLIP_CONCEPTS.values() if any(t.startswith(w) or w.startswith(t) for t in tokens for w in words if len(t) >= 3)]
    search = {w for words in concepts for w in words} or {t for t in tokens if len(t) >= 3}
    matches = [n for n in names if any(w in normalize_text(n) for w in search)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise Clarification("clip_ambiguous", f"Several clips match '{query}'. Which one?",
                            [{"id": n, "label": n, "why": "clip"} for n in matches])
    raise CommandRejected("clip_not_found", f"{label} has no '{query}' clip. Available: {', '.join(names)}.", {"available": names})


def _clamp_position(position: Sequence[float], notes: List[str]) -> List[float]:
    result = []
    for axis, (value, low, high) in enumerate(zip(position, LIMITS["position_min"], LIMITS["position_max"])):
        clamped = min(max(value, low), high)
        if clamped != value:
            notes.append(f"{'xyz'[axis]} limited to the workspace edge ({clamped:+.2f} m).")
        result.append(clamped)
    return q3(result)


def placement(state: Dict[str, Any], width: float) -> List[float]:
    """Deterministic non-overlapping default placement along x."""
    if not state["order"]:
        return [0.0, 0.0, 0.0]
    right = max(o["transform"]["position"][0] + object_size(o)[0] / 2 for o in state["objects"].values())
    x = right + 0.3 + width / 2
    if x > LIMITS["position_max"][0]:
        left = min(o["transform"]["position"][0] - object_size(o)[0] / 2 for o in state["objects"].values())
        x = left - 0.3 - width / 2
    if x < LIMITS["position_min"][0]:
        x = 0.0
    return [quantize(x), 0.0, 0.0]


def _unique_label(state: Dict[str, Any], label: str) -> str:
    existing = {o["label"] for o in state["objects"].values()}
    if label not in existing:
        return label
    number = 2
    while f"{label} ({number})"[:80] in existing:
        number += 1
    return f"{label} ({number})"[:80]


def _asset_error(exc: Exception) -> CommandRejected:
    code = getattr(exc, "code", "asset_error")
    return CommandRejected(code, str(exc))


def _resolve_asset(request: rq.AddAsset, assets: AssetRegistry) -> Dict[str, Any]:
    try:
        if request.fixture:
            return assets.register_fixture()
        if request.asset_id:
            return assets.summary(assets.record(request.asset_id))
        assert request.form is not None
        if request.form.project_id is None:
            if request.form.version != "latest":
                raise CommandRejected("form_project_required", "Name the FORM project for that version.")
            return assets.latest_form()
        return assets.register_form(request.form.project_id, request.form.version)
    except (AssetError, FormLibraryError) as exc:
        raise _asset_error(exc) from exc


def _version_selector(obj: Dict[str, Any], selector: str, assets: AssetRegistry) -> str:
    form = obj["asset"].get("form")
    if not form:
        raise CommandRejected("not_form", f"{obj['label']} is not a FORM character, so it has no versions.")
    if selector in {"latest", "best"}:
        return selector
    try:
        versions = [v for v in assets.form.versions(form["project_id"]) if v["kind"] == "production"]
    except FormLibraryError as exc:
        raise _asset_error(exc) from exc
    if selector in {"previous", "next"}:
        loadable = [v for v in versions if v["loadable"]]
        ids = [v["id"] for v in loadable]
        if form["version_id"] not in ids:
            raise CommandRejected("version_unknown", "The current version is no longer listed by FORM.")
        position = ids.index(form["version_id"]) + (-1 if selector == "previous" else 1)
        if not 0 <= position < len(ids):
            raise CommandRejected("version_edge", f"There is no {selector} verified FORM version.")
        return ids[position]
    match = VERSION_LABEL.match(selector.strip())
    if match:
        index = int(match.group(1))
        chosen = next((v for v in versions if v["index"] == index), None)
        if not chosen:
            raise CommandRejected("version_unknown", f"FORM project has no V{index:02d}.")
        return chosen["id"]
    return selector


def compile_request(request: Any, ctx: CompileContext) -> Prepared:
    state = ctx.state
    prepared = Prepared(request=request.model_dump(exclude_none=True))
    if request.type in rq.CONFIRM_REQUESTS:
        prepared.risk = "confirm"

    def target(ref: rq.ObjectRef) -> Dict[str, Any]:
        key = resolve(ref, state, ctx.events, ctx.anchors)
        prepared.targets.append(key)
        return state["objects"][key]

    kind = request.type
    if kind in {"history.undo", "history.redo"}:
        prepared.history = kind.split(".")[1]
        return prepared
    if kind == "scene.add_asset":
        asset = _resolve_asset(request, ctx.assets)
        notes: List[str] = []
        position = _clamp_position(request.position, notes) if request.position else placement(state, asset["normalization"]["size"][0])
        prepared.notes.extend(notes)
        transform = default_transform()
        transform["position"] = position
        object_id = ctx.new_id()
        obj = new_object(object_id, asset, _unique_label(state, request.label or asset["label"]), transform)
        prepared.commands = [{"type": "object.add", "object": obj}, {"type": "selection.set", "object_ids": [object_id]}]
        prepared.targets.append(object_id)
        if asset.get("form", {}) and asset["form"].get("experimental"):
            prepared.notes.append("Experimental FORM local shape: unrigged, not a production character.")
        return prepared
    if kind == "selection.select":
        ids = [target(request.target)["id"]] if request.target else []
        prepared.commands = [{"type": "selection.set", "object_ids": ids}]
        return prepared
    if kind == "view.inspect":
        object_id = target(request.target)["id"] if request.target else None
        prepared.commands = [{"type": "view.inspect", "object_id": object_id}]
        return prepared
    if kind == "view.set":
        prepared.commands = [{"type": "view.set", **request.model_dump(exclude_none=True, exclude={"type"})}]
        return prepared
    obj = target(request.target)
    if kind == "scene.remove":
        prepared.commands = [{"type": "object.remove", "object_id": obj["id"]}]
    elif kind == "object.transform":
        prepared.lease_id = request.lease_id
        current = obj["transform"]
        transform = {"position": list(current["position"]), "rotation": list(current["rotation"]), "scale": current["scale"]}
        notes: List[str] = []
        mode = request.mode
        if mode == "set":
            transform = request.transform.model_dump()
        elif mode == "translate":
            transform["position"] = _clamp_position([a + b for a, b in zip(current["position"], request.delta)], notes)
        elif mode == "rotate":
            transform["rotation"] = rotate_world(current["rotation"], request.axis, request.degrees)
        elif mode == "scale":
            wanted = current["scale"] * request.factor
            scale = min(max(wanted, LIMITS["scale_min"]), LIMITS["scale_max"])
            if abs(scale - current["scale"]) < 1e-6:
                raise CommandRejected("scale_limit", f"{obj['label']} is already at the {'largest' if request.factor > 1 else 'smallest'} supported size.")
            if scale != wanted:
                notes.append(f"Scale limited to {scale:g}x.")
            transform["scale"] = quantize(scale)
        elif mode == "reset":
            transform = default_transform()
        elif mode == "center":
            transform["position"] = [0.0, 0.0, 0.0]
        elif mode == "to_anchor":
            anchor = ctx.anchors.get(request.anchor or "")
            if not anchor:
                hand = "right" if request.anchor == "right_hand" else "left"
                raise Clarification("anchor_unavailable", f"I can't see your {hand} hand right now. Show it to the camera and try again.")
            ax, ay, _ = anchor["position"]
            transform["position"] = _clamp_position([ax, ay, current["position"][2]], notes)
        prepared.notes.extend(notes)
        prepared.commands = [{"type": "object.transform", "object_id": obj["id"], "transform": transform}]
    elif kind == "object.visibility":
        prepared.commands = [{"type": "object.visibility", "object_id": obj["id"], "visible": request.visible}]
    elif kind == "object.display":
        flags = request.model_dump(exclude_none=True, include={"skeleton", "form_hud", "bounds"})
        prepared.commands = [{"type": "object.display", "object_id": obj["id"], **flags}]
    elif kind == "animation.control":
        animation = obj["animation"]
        speed = request.speed if request.speed is not None else animation["speed"]
        if request.action == "play":
            clips = obj["asset"].get("clips", [])
            if request.clip:
                clip = match_clip(request.clip, clips, obj["label"])
            elif animation["clip"]:
                clip = animation["clip"]
            elif len(clips) == 1:
                clip = clips[0]["name"]
            elif not clips:
                raise CommandRejected("no_clips", f"{obj['label']} has no animation clips.", {"available": []})
            else:
                raise Clarification("clip_choice", f"{obj['label']} has several clips. Which one?",
                                    [{"id": c["name"], "label": c["name"], "why": "clip"} for c in clips])
            prepared.commands = [{"type": "object.animation", "object_id": obj["id"], "clip": clip, "playing": True, "speed": speed}]
        elif request.action == "pause":
            if not animation["clip"]:
                raise CommandRejected("not_playing", f"{obj['label']} has no active animation.")
            prepared.commands = [{"type": "object.animation", "object_id": obj["id"], "clip": animation["clip"], "playing": False, "speed": speed}]
        else:
            prepared.commands = [{"type": "object.animation", "object_id": obj["id"], "clip": None, "playing": False, "speed": speed}]
    elif kind == "object.version":
        selector = _version_selector(obj, request.version, ctx.assets)
        form = obj["asset"]["form"]
        try:
            asset = ctx.assets.register_form(form["project_id"], selector)
        except (AssetError, FormLibraryError) as exc:
            raise _asset_error(exc) from exc
        if asset["asset_id"] == obj["asset"]["asset_id"] and asset["form"]["version_id"] == form["version_id"]:
            raise CommandRejected("same_version", f"{obj['label']} already shows {form['version_label']}.")
        label = f"{asset['form']['project_name']} {asset['form']['version_label']}"[:80]
        prepared.commands = [{"type": "object.asset", "object_id": obj["id"], "asset": asset, "label": _unique_label({**state, "objects": {k: v for k, v in state["objects"].items() if k != obj["id"]}}, label)}]
    elif kind == "object.rename":
        prepared.commands = [{"type": "object.rename", "object_id": obj["id"], "label": request.label}]
    else:  # pragma: no cover - the discriminated union makes this unreachable
        raise CommandRejected("unknown_request", f"Unsupported request {kind!r}.")
    return prepared
