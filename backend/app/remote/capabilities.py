"""Device capabilities: what a connected device can provide right now.

Identity (who the device is, what the owner allows it to do) lives in the
device registry. Capabilities are separate, dynamic facts reported by the
device for the current session — a phone's camera can become ``denied`` when
the user refuses the permission prompt, or ``active`` while hand tracking runs.

The registry answers "which connected device can provide X?" from live
sessions only; a device that is offline or stale provides nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

CAPABILITIES: Dict[str, str] = {
    "camera": "A camera the device can open locally.",
    "microphone": "A microphone the device can open locally.",
    "touch": "A touch screen.",
    "pointer": "A mouse or trackpad pointer.",
    "keyboard": "A hardware or on-screen keyboard.",
    "hand_tracking": "On-device hand landmark detection (camera frames stay on the device).",
    "gesture": "On-device gesture interpretation into scene intents.",
    "orientation": "Device orientation / motion sensors.",
    "display": "A screen that renders the synchronized scene.",
    "speech_output": "On-device speech synthesis.",
    "voice_input": "Speech recognition producing transcripts (engine reported in details).",
    "notifications": "Can surface notifications to its user.",
    "approval_surface": "Can show pending approvals and collect a decision.",
}

STATES = ("available", "active", "unavailable", "denied")
USABLE = ("active", "available")
MAX_DETAIL_BYTES = 1024


class CapabilityError(ValueError):
    pass


@dataclass
class Capability:
    name: str
    state: str = "available"
    detail: Dict[str, Any] = field(default_factory=dict)

    def public(self) -> Dict[str, Any]:
        return {"name": self.name, "state": self.state, "detail": dict(self.detail)}


def parse(items: Iterable[Any]) -> Dict[str, Capability]:
    """Validate a device's capability report. Unknown names are rejected, not ignored."""
    result: Dict[str, Capability] = {}
    for item in items:
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict):
            raise CapabilityError("A capability must be a name or an object.")
        name = item.get("name")
        if name not in CAPABILITIES:
            raise CapabilityError(f"Unknown capability: {str(name)[:40]}")
        state = item.get("state", "available")
        if state not in STATES:
            raise CapabilityError(f"Invalid state for {name}: {str(state)[:20]}")
        detail = item.get("detail") or {}
        if not isinstance(detail, dict):
            raise CapabilityError(f"Capability detail for {name} must be an object.")
        encoded = json.dumps(detail, ensure_ascii=False, allow_nan=False, default=str)
        if len(encoded.encode("utf-8")) > MAX_DETAIL_BYTES:
            raise CapabilityError(f"Capability detail for {name} is too large.")
        result[name] = Capability(name, state, json.loads(encoded))
    if len(result) > len(CAPABILITIES):
        raise CapabilityError("Too many capabilities.")
    return result


@dataclass
class Provider:
    device: Dict[str, Any]
    session_id: str
    capability: Capability
    last_seen_age: float

    def public(self) -> Dict[str, Any]:
        return {"device": dict(self.device), "session_id": self.session_id, "capability": self.capability.public(),
                "last_seen_seconds": round(self.last_seen_age, 1)}


class CapabilityRegistry:
    """Read-only view over live sessions; the sessions own the capability sets."""

    def __init__(self, sessions: Callable[[], Iterable[Any]], monotonic: Callable[[], float]) -> None:
        self._sessions = sessions
        self._monotonic = monotonic

    def providers(self, capability: str) -> List[Provider]:
        if capability not in CAPABILITIES:
            raise CapabilityError(f"Unknown capability: {capability[:40]}")
        now = self._monotonic()
        found: List[Provider] = []
        for session in self._sessions():
            if session.state != "open":
                continue
            item = session.capabilities.get(capability)
            if item is None or item.state not in USABLE:
                continue
            found.append(Provider(session.device_public(), session.id, item, now - session.last_seen))
        found.sort(key=lambda p: (USABLE.index(p.capability.state), p.last_seen_age))
        return found

    def summary(self) -> List[Dict[str, Any]]:
        now = self._monotonic()
        rows = []
        for session in self._sessions():
            if session.state == "closed":
                continue
            rows.append({"device": session.device_public(), "session_id": session.id, "state": session.state,
                         "last_seen_seconds": round(now - session.last_seen, 1),
                         "capabilities": [c.public() for c in session.capabilities.values()]})
        return rows

    def describe(self, capability: Optional[str] = None, language: str = "en") -> str:
        """A short natural-language answer for AKASHI."""
        tr = language == "tr"
        if capability:
            providers = self.providers(capability)
            if not providers:
                return (f"Şu anda '{capability}' sağlayabilen bağlı bir cihaz yok." if tr
                        else f"No connected device can provide '{capability}' right now.")
            names = ", ".join(f"{p.device['name']} ({p.capability.state})" for p in providers)
            return f"'{capability}' sağlayabilen cihazlar: {names}." if tr else f"Devices that can provide '{capability}': {names}."
        rows = [r for r in self.summary() if r["state"] == "open"]
        if not rows:
            return "Şu anda bağlı uzak cihaz yok." if tr else "No remote device is connected right now."
        parts = []
        for row in rows:
            usable = [c["name"] for c in row["capabilities"] if c["state"] in USABLE]
            parts.append(f"{row['device']['name']}: {', '.join(usable) or ('yetenek yok' if tr else 'no capabilities')}")
        return ("Bağlı cihazlar — " if tr else "Connected devices — ") + "; ".join(parts) + "."
