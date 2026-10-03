"""Spatial sessions: persistent scene history plus ephemeral interaction state.

Persistent (in the action log): every scene change, its origin and its patches.

Ephemeral (memory only, never replayed):

* **Leases** — a hand that grabs an object holds a short, renewable lease. While
  it is held, other origins (voice, tools, UI) cannot change that object and
  undo/redo wait, so two input methods never fight over one object.
* **Presence** — the latest hand anchors projected onto the interaction plane,
  used to resolve "move it to my right hand". Stale anchors are ignored.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.history import ActionHistory, ActionLog, LogCorrupted
from app.history.engine import CommandRejected
from app.spatial.domain import SpatialSceneDomain
from app.spatial.model import SESSION_ID, initial_scene

LEASE_TTL_SECONDS = 4.0
PRESENCE_TTL_SECONDS = 2.0
ANCHORS = ("left_hand", "right_hand")


@dataclass
class Lease:
    id: str
    object_id: str
    origin: str
    expires: float
    started: float

    def public(self, now: float) -> Dict[str, Any]:
        return {"id": self.id, "object_id": self.object_id, "origin": self.origin,
                "expires_in": round(max(0.0, self.expires - now), 3)}


class SessionCorrupted(RuntimeError):
    pass


class SpatialSession:
    def __init__(self, history: ActionHistory, monotonic: Callable[[], float] = time.monotonic,
                 recovered_torn_tail: bool = False) -> None:
        self.history = history
        self.monotonic = monotonic
        self.lock = threading.RLock()
        self.leases: Dict[str, Lease] = {}
        self.presence: Dict[str, Any] = {}
        self.presence_at: Optional[float] = None
        self.last_client_seen: Optional[float] = None
        self.recovered_torn_tail = recovered_torn_tail
        self.pending_confirmations: Dict[str, Dict[str, Any]] = {}

    @property
    def id(self) -> str:
        return self.history.stream_id

    @property
    def label(self) -> str:
        return self.history.log.header.get("metadata", {}).get("label", "Spatial Lab")

    # Leases -----------------------------------------------------------------------
    def _expire(self) -> None:
        now = self.monotonic()
        for key in [k for k, lease in self.leases.items() if lease.expires <= now]:
            del self.leases[key]

    def lease_for(self, object_id: str) -> Optional[Lease]:
        self._expire()
        return self.leases.get(object_id)

    def begin_lease(self, object_id: str, origin: str) -> Lease:
        self._expire()
        if object_id not in self.history.state["objects"]:
            raise CommandRejected("object_not_found", "The target object is not in this scene.")
        if object_id in self.leases:
            raise CommandRejected("object_busy", "That object is already being manipulated.")
        now = self.monotonic()
        lease = Lease("lease-" + uuid.uuid4().hex[:16], object_id, origin, now + LEASE_TTL_SECONDS, now)
        self.leases[object_id] = lease
        return lease

    def find_lease(self, lease_id: str) -> Lease:
        self._expire()
        for lease in self.leases.values():
            if lease.id == lease_id:
                return lease
        raise CommandRejected("lease_expired", "The manipulation lease expired; the object was released.")

    def renew_lease(self, lease_id: str) -> Lease:
        lease = self.find_lease(lease_id)
        lease.expires = self.monotonic() + LEASE_TTL_SECONDS
        return lease

    def end_lease(self, lease_id: str) -> bool:
        self._expire()
        for key, lease in list(self.leases.items()):
            if lease.id == lease_id:
                del self.leases[key]
                return True
        return False

    def active_leases(self) -> List[Lease]:
        self._expire()
        return list(self.leases.values())

    # Presence ---------------------------------------------------------------------
    def set_presence(self, anchors: Dict[str, Any]) -> None:
        self.presence = {k: v for k, v in anchors.items() if k in ANCHORS}
        self.presence_at = self.monotonic()
        self.last_client_seen = self.presence_at

    def fresh_anchors(self) -> Dict[str, Any]:
        if self.presence_at is None or self.monotonic() - self.presence_at > PRESENCE_TTL_SECONDS:
            return {}
        return dict(self.presence)

    def touch_client(self) -> None:
        self.last_client_seen = self.monotonic()


class SessionStore:
    def __init__(self, root: Optional[Path], *, max_events: int = 10_000,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self.root = Path(root) if root is not None else None
        if self.root is not None:
            self.root.mkdir(parents=True, exist_ok=True)
        self.domain = SpatialSceneDomain()
        self.max_events = max_events
        self.monotonic = monotonic
        self._sessions: Dict[str, SpatialSession] = {}
        self._corrupted: Dict[str, str] = {}
        self._lock = threading.RLock()

    def create(self, label: str = "Spatial Lab") -> SpatialSession:
        session_id = "spatial-" + uuid.uuid4().hex[:16]
        directory = self.root / session_id if self.root is not None else None
        history = ActionHistory.create(self.domain, session_id, initial_scene(), directory=directory,
                                       metadata={"label": re.sub(r"\s+", " ", label).strip()[:80] or "Spatial Lab"},
                                       max_events=self.max_events)
        session = SpatialSession(history, self.monotonic)
        with self._lock:
            self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> SpatialSession:
        if not isinstance(session_id, str) or not SESSION_ID.match(session_id):
            raise KeyError("Spatial session id is invalid.")
        with self._lock:
            if session_id in self._sessions:
                return self._sessions[session_id]
            if session_id in self._corrupted:
                raise SessionCorrupted(self._corrupted[session_id])
            directory = self.root / session_id if self.root is not None else None
            if directory is None or not directory.is_dir():
                raise KeyError("Spatial session was not found.")
            try:
                log = ActionLog.open(directory)
                history = ActionHistory.restore(self.domain, log, max_events=self.max_events)
            except LogCorrupted as exc:
                reason = f"Session history failed integrity checks ({exc.reason}). It was left untouched; start a new session."
                self._corrupted[session_id] = reason
                raise SessionCorrupted(reason) from exc
            session = SpatialSession(history, self.monotonic, recovered_torn_tail=log.torn_tail_recovered)
            self._sessions[session_id] = session
            return session

    def list(self) -> List[Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        with self._lock:
            for session in self._sessions.values():
                result[session.id] = self._describe(session.id, session.label, session.history.log.header.get("created_at"), session.history.revision)
        if self.root is not None:
            for directory in sorted(self.root.iterdir()):
                if directory.name in result or not SESSION_ID.match(directory.name):
                    continue
                try:
                    header = json.loads((directory / "header.json").read_text(encoding="utf-8"))
                    with (directory / "events.jsonl").open("rb") as stream:
                        revision = sum(1 for _ in stream)
                    result[directory.name] = self._describe(directory.name, header.get("metadata", {}).get("label", "Spatial Lab"), header.get("created_at"), revision)
                except (OSError, ValueError):
                    result[directory.name] = {"id": directory.name, "label": "Unreadable session", "created_at": None, "revision": None, "readable": False}
        return sorted(result.values(), key=lambda s: s.get("created_at") or "", reverse=True)

    @staticmethod
    def _describe(session_id: str, label: str, created_at: Any, revision: Any) -> Dict[str, Any]:
        return {"id": session_id, "label": label, "created_at": created_at, "revision": revision, "readable": True}
