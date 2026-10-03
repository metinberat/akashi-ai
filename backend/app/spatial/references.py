"""Resolve object references against the authoritative scene.

Resolution never guesses between equally plausible objects. When a reference
does not single out one object it raises ``Clarification`` with candidates, so
callers ask the user instead of mutating a random object.

Spatial terms use the fixed V1 viewing direction: the camera looks along -Z, so
"left" means smaller x on screen (the user's left in the mirrored camera view).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from app.spatial.model import object_size
from app.spatial.requests import ObjectRef

TIE_DISTANCE = 0.05  # metres; closer than this on screen counts as "same place"
TIE_RATIO = 0.05     # relative size difference treated as "same size"


class Clarification(Exception):
    def __init__(self, code: str, question: str, candidates: Optional[List[Dict[str, Any]]] = None) -> None:
        self.code = code
        self.question = question
        self.candidates = candidates or []
        super().__init__(question)


def candidate(obj: Dict[str, Any], why: str = "") -> Dict[str, Any]:
    x = obj["transform"]["position"][0]
    return {"id": obj["id"], "label": obj["label"], "position": "left" if x < -0.3 else "right" if x > 0.3 else "center", "why": why}


def _visible(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [state["objects"][k] for k in state["order"] if state["objects"][k]["visible"]]


def _all(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [state["objects"][k] for k in state["order"]]


def _single(objects: Sequence[Dict[str, Any]], code: str, question: str) -> str:
    if len(objects) == 1:
        return objects[0]["id"]
    if not objects:
        raise Clarification(code + "_none", question.split("|")[0])
    raise Clarification(code + "_ambiguous", question.split("|")[-1], [candidate(o) for o in objects])


def last_target(events: Sequence[Dict[str, Any]], state: Dict[str, Any], categories: Optional[set] = None) -> Optional[str]:
    for event in reversed(events):
        if event.get("kind") != "command" or not event.get("targets"):
            continue
        if categories is not None and event.get("category") not in categories:
            continue
        if event.get("category") == "selection" and categories is None:
            continue
        target = event["targets"][0]
        if target in state["objects"]:
            return target
    return None


def _extreme(objects: List[Dict[str, Any]], key, largest: bool, tie, code: str, what: str) -> str:
    if not objects:
        raise Clarification(code + "_none", "There are no visible objects in the scene.")
    if len(objects) == 1:
        return objects[0]["id"]
    ranked = sorted(objects, key=key, reverse=largest)
    first, second = key(ranked[0]), key(ranked[1])
    if tie(first, second):
        tied = [o for o in ranked if tie(key(o), first)]
        raise Clarification(code + "_tie", f"More than one object is the {what}. Which one do you mean?", [candidate(o) for o in tied])
    return ranked[0]["id"]


def resolve(ref: ObjectRef, state: Dict[str, Any], events: Sequence[Dict[str, Any]] = (),
            anchors: Optional[Dict[str, Any]] = None) -> str:
    objects = state["objects"]
    if ref.id is not None:
        if ref.id not in objects:
            raise Clarification("not_found", "That object is no longer in the scene.")
        return ref.id
    kind = ref.ref
    if kind == "selected":
        return _single([objects[k] for k in state["selection"]], "selected", "Nothing is selected.|Several objects are selected.")
    if kind == "only":
        return _single(_visible(state), "only", "The scene is empty.|There is more than one object. Which one?")
    if kind in {"last_touched", "last_moved"}:
        target = last_target(events, state, {"transform"} if kind == "last_moved" else None)
        if target is None:
            raise Clarification(kind + "_none", "I don't know which object you changed last." if kind == "last_touched" else "Nothing has been moved yet.")
        return target
    if kind == "deictic":
        if len(state["selection"]) == 1:
            return state["selection"][0]
        visible = _visible(state)
        if len(visible) == 1:
            return visible[0]["id"]
        if not visible:
            raise Clarification("deictic_none", "The scene is empty.")
        target = last_target(events, state)
        if target is not None:
            return target
        raise Clarification("deictic_ambiguous", "Which object do you mean?", [candidate(o) for o in visible])
    if kind in {"leftmost", "rightmost"}:
        return _extreme(_visible(state), lambda o: o["transform"]["position"][0], kind == "rightmost",
                        lambda a, b: abs(a - b) < TIE_DISTANCE, kind, "furthest " + kind[:-4])
    if kind in {"largest", "smallest"}:
        return _extreme(_visible(state), lambda o: max(object_size(o)), kind == "largest",
                        lambda a, b: abs(a - b) <= TIE_RATIO * max(abs(a), abs(b), 1e-9), kind, kind)
    if kind == "form":
        form_objects = [o for o in _all(state) if o["asset"].get("source") == "form"]
        if len(form_objects) > 1:
            selected = [o for o in form_objects if o["id"] in state["selection"]]
            if len(selected) == 1:
                return selected[0]["id"]
        return _single(form_objects, "form", "There is no FORM character in the scene.|Several FORM characters are in the scene. Which one?")
    if kind == "latest_version":
        form_objects = [o for o in _all(state) if o["asset"].get("form")]
        if not form_objects:
            raise Clarification("latest_version_none", "There is no FORM version in the scene.")
        return _extreme(form_objects, lambda o: o["asset"]["form"].get("created_at") or "", True,
                        lambda a, b: a == b, "latest_version", "latest version")
    if kind == "label":
        needle = (ref.label or "").casefold().strip()
        matches = [o for o in _all(state) if needle in o["label"].casefold()
                   or needle in str((o["asset"].get("form") or {}).get("project_name", "")).casefold()]
        exact = [o for o in matches if o["label"].casefold() == needle]
        return _single(exact or matches, "label", f"No object is called '{ref.label}'.|Several objects match '{ref.label}'. Which one?")
    if kind == "nearest_anchor":
        anchor = (anchors or {}).get(ref.anchor or "")
        if not anchor:
            raise Clarification("anchor_unavailable", "I can't see that hand right now.")
        px, py, _ = anchor["position"]
        visible = _visible(state)
        return _extreme(visible, lambda o: -((o["transform"]["position"][0] - px) ** 2 + (o["transform"]["position"][1] + max(object_size(o)) / 2 - py) ** 2),
                        True, lambda a, b: abs(a - b) < TIE_DISTANCE ** 2, "nearest", "closest to your hand")
    raise Clarification("unsupported_reference", "That kind of reference is not supported.")
