"""Reversible, verifiable patches over plain JSON documents.

A patch records the value at a path before and after a change. Dictionaries are
diffed key by key; lists and scalars are replaced atomically, which keeps
patches deterministic and easy to invert. Applying a patch first checks that the
document still holds the recorded ``before`` value, so a stale or corrupted
patch is rejected instead of silently producing a different state.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Sequence

from app.history.canonical import canonical_json

Path = List[Any]
Patch = Dict[str, Any]


class PatchConflict(ValueError):
    """The document does not match the state a patch was recorded against."""


def _same(left: Any, right: Any) -> bool:
    return canonical_json(left) == canonical_json(right)


def diff(before: Any, after: Any, path: Path | None = None) -> List[Patch]:
    path = list(path or [])
    if isinstance(before, dict) and isinstance(after, dict):
        patches: List[Patch] = []
        for key in sorted(set(before) | set(after), key=str):
            child = path + [key]
            if key not in after:
                patches.append({"op": "remove", "path": child, "before": copy.deepcopy(before[key])})
            elif key not in before:
                patches.append({"op": "add", "path": child, "after": copy.deepcopy(after[key])})
            else:
                patches.extend(diff(before[key], after[key], child))
        return patches
    if _same(before, after):
        return []
    if not path:
        raise ValueError("Root documents must be objects to be patched.")
    return [{"op": "replace", "path": path, "before": copy.deepcopy(before), "after": copy.deepcopy(after)}]


def _parent(document: Any, path: Sequence[Any]) -> Any:
    node = document
    for key in path[:-1]:
        if not isinstance(node, dict) or key not in node:
            raise PatchConflict(f"Patch path {list(path)} does not exist.")
        node = node[key]
    if not isinstance(node, dict):
        raise PatchConflict(f"Patch parent {list(path[:-1])} is not an object.")
    return node


def apply(document: Dict[str, Any], patches: Sequence[Patch]) -> Dict[str, Any]:
    """Return a new document with patches applied after verifying preconditions."""
    result = copy.deepcopy(document)
    for patch in patches:
        path = patch.get("path")
        if not isinstance(path, list) or not path:
            raise PatchConflict("Patch path must be a non-empty list.")
        parent = _parent(result, path)
        key = path[-1]
        op = patch.get("op")
        if op == "add":
            if key in parent:
                raise PatchConflict(f"Patch add target {path} already exists.")
            parent[key] = copy.deepcopy(patch["after"])
        elif op == "remove":
            if key not in parent or not _same(parent[key], patch["before"]):
                raise PatchConflict(f"Patch remove target {path} does not match.")
            del parent[key]
        elif op == "replace":
            if key not in parent or not _same(parent[key], patch["before"]):
                raise PatchConflict(f"Patch replace target {path} does not match.")
            parent[key] = copy.deepcopy(patch["after"])
        else:
            raise PatchConflict(f"Unknown patch operation {op!r}.")
    return result


def invert(patches: Sequence[Patch]) -> List[Patch]:
    inverted: List[Patch] = []
    for patch in reversed(patches):
        op = patch["op"]
        if op == "add":
            inverted.append({"op": "remove", "path": list(patch["path"]), "before": copy.deepcopy(patch["after"])})
        elif op == "remove":
            inverted.append({"op": "add", "path": list(patch["path"]), "after": copy.deepcopy(patch["before"])})
        else:
            inverted.append({"op": "replace", "path": list(patch["path"]),
                             "before": copy.deepcopy(patch["after"]), "after": copy.deepcopy(patch["before"])})
    return inverted
