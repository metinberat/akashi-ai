"""Tamper-evident audit trail for remote presence and approvals.

Reuses ``app.history.ActionLog`` (hash-chained, fsync'd, torn-tail recovery):
pairings, session handshakes and closures, revocations, grant changes,
refused messages and approval decisions — each with its device and session.

A log that fails its integrity check is never repaired. The audit trail then
reports ``broken`` and every operation that must be audited (pairing, opening
sessions, approval decisions) is refused until the owner moves it aside.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.history.log import ActionLog, LogCorrupted

STREAM = "akashi.remote.audit"
SEGMENT_EVENTS = 50_000


class AuditUnavailable(RuntimeError):
    pass


class AuditLog:
    def __init__(self, directory: Optional[Path], clock: Callable[[], str] = lambda: datetime.now(timezone.utc).isoformat()) -> None:
        self.directory = Path(directory) if directory is not None else None
        self.clock = clock
        self.broken: Optional[str] = None
        self._lock = threading.Lock()
        self._suppressed: Dict[str, float] = {}
        self.log = self._open_latest()

    def _segments(self) -> List[Path]:
        if self.directory is None or not self.directory.is_dir():
            return []
        return sorted(p for p in self.directory.iterdir() if p.is_dir() and p.name.startswith("segment-"))

    def _open_latest(self) -> Optional[ActionLog]:
        segments = self._segments()
        try:
            if segments:
                return ActionLog.open(segments[-1])
            return self._create(1, None)
        except LogCorrupted as exc:
            self.broken = f"Remote audit log failed its integrity check ({exc.reason}); it was left untouched."
            return None

    def _create(self, number: int, previous: Optional[str]) -> ActionLog:
        directory = None
        if self.directory is not None:
            self.directory.mkdir(parents=True, exist_ok=True)
            directory = self.directory / f"segment-{number:04d}"
        return ActionLog.create({"stream": STREAM, "segment": number, "previous_head": previous, "created_at": self.clock()}, directory)

    def record(self, kind: str, /, **detail: Any) -> Dict[str, Any]:
        with self._lock:
            if self.log is None:
                raise AuditUnavailable(self.broken or "Remote audit log is unavailable.")
            if len(self.log.events) >= SEGMENT_EVENTS:
                self.log = self._create(int(self.log.header.get("segment", 1)) + 1, self.log.head)
            return self.log.append({**detail, "stream": STREAM, "at": self.clock(), "kind": kind})

    def record_limited(self, key: str, interval: float, kind: str, /, **detail: Any) -> Optional[Dict[str, Any]]:
        """Record at most once per ``interval`` seconds per key (refusal floods stay bounded)."""
        now = time.monotonic()
        with self._lock:
            last = self._suppressed.get(key)
            if last is not None and now - last < interval:
                return None
            self._suppressed[key] = now
            if len(self._suppressed) > 4096:
                self._suppressed.clear()
        try:
            return self.record(kind, **detail)
        except AuditUnavailable:
            return None

    def require(self) -> None:
        if self.log is None:
            raise AuditUnavailable(self.broken or "Remote audit log is unavailable.")

    def recent(self, after: int = 0, limit: int = 200) -> Dict[str, Any]:
        with self._lock:
            if self.log is None:
                return {"available": False, "reason": self.broken, "events": []}
            events = [e for e in self.log.events if e["seq"] > after][:limit]
            return {"available": True, "segment": self.log.header.get("segment", 1), "head": self.log.head, "events": events}

    def verify(self) -> Dict[str, Any]:
        with self._lock:
            if self.log is None:
                return {"verified": False, "reason": self.broken}
            try:
                # Re-read from disk: an in-memory check alone would miss edits to the file.
                fresh = ActionLog.open(self.log.directory) if self.log.directory is not None else self.log
                fresh.verify()
            except LogCorrupted as exc:
                return {"verified": False, "reason": exc.reason}
            if fresh.head != self.log.head:
                return {"verified": False, "reason": "On-disk audit log differs from the running process."}
            return {"verified": True, "events": len(fresh.events), "head": fresh.head}
