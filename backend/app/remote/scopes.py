"""Permission scopes a remote device can hold.

Scopes describe what a device may ask Core to do. They are granted by the owner
when a pairing code is created (or changed later), never chosen by the device.
A session holds the intersection of what the device requested and what the
owner granted, re-evaluated immediately when the grant changes.

There is deliberately no scope for general computer control (Windows Agent
actions, browser automation, file operations): a remote presence device cannot
obtain those in this version, whatever it requests.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Iterable, List

SCOPES: Dict[str, str] = {
    "spatial.view": "See the Spatial Lab scene, its history, leases and the devices in it.",
    "spatial.control": "Change the Spatial Lab scene (select, move, rotate, scale, display, animation, FORM versions, undo/redo).",
    "spatial.presence": "Share hand anchors and cursors derived on the device (never camera frames).",
    "voice.spatial": "Speak or type scene instructions to AKASHI; they run through the Spatial Lab command path.",
    "assistant.chat": "Converse with AKASHI; live actions are limited to scene actions.",
    "approvals.spatial": "See and decide pending Spatial Lab confirmations.",
    "approvals.general": "See and decide every pending AKASHI approval (tasks and autonomy included).",
}

# A scope that cannot be used without another one.
REQUIRES: Dict[str, FrozenSet[str]] = {
    "spatial.control": frozenset({"spatial.view"}),
    "spatial.presence": frozenset({"spatial.view"}),
    "voice.spatial": frozenset({"spatial.view", "spatial.control"}),
    "approvals.general": frozenset({"approvals.spatial"}),
}

PRESETS: Dict[str, List[str]] = {
    "spatial-remote": ["spatial.view", "spatial.control", "spatial.presence", "voice.spatial", "approvals.spatial"],
    "spatial-viewer": ["spatial.view"],
    "approver": ["approvals.spatial", "approvals.general"],
}

OWNER_SCOPES: FrozenSet[str] = frozenset(SCOPES)


class ScopeError(ValueError):
    pass


def normalize(scopes: Iterable[str]) -> FrozenSet[str]:
    """Validate scope names and add the scopes they require."""
    result = set()
    for scope in scopes:
        if not isinstance(scope, str) or scope not in SCOPES:
            raise ScopeError(f"Unknown scope: {str(scope)[:60]}")
        result.add(scope)
    changed = True
    while changed:
        changed = False
        for scope in list(result):
            missing = REQUIRES.get(scope, frozenset()) - result
            if missing:
                result |= missing
                changed = True
    return frozenset(result)


def from_preset(preset: str) -> FrozenSet[str]:
    if preset not in PRESETS:
        raise ScopeError(f"Unknown scope preset: {preset[:60]}")
    return normalize(PRESETS[preset])


def effective(requested: Iterable[str] | None, granted: Iterable[str]) -> FrozenSet[str]:
    """What a session may use: requested ∩ granted, dropping scopes whose prerequisites were lost."""
    granted_set = frozenset(granted)
    wanted = set(granted_set if requested is None else frozenset(requested) & granted_set)
    # A requested scope brings its prerequisites along when the owner granted them.
    for scope in list(wanted):
        wanted |= REQUIRES.get(scope, frozenset()) & granted_set
    result = set(wanted)
    changed = True
    while changed:
        changed = False
        for scope in list(result):
            if not REQUIRES.get(scope, frozenset()) <= result:
                result.discard(scope)
                changed = True
    return frozenset(result)


def catalog() -> List[Dict[str, object]]:
    return [{"scope": name, "description": text, "requires": sorted(REQUIRES.get(name, ()))} for name, text in SCOPES.items()]
