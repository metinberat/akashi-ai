"""Short-lived remote sessions and their delivery queues.

A session is opened by a successful device handshake (or by the owner with the
API token) and gets its own random credential, stored only as a SHA-256 hash.
High-frequency traffic is authenticated with that credential, so the slow,
salted device-secret check runs once per session, never per message.

Lifecycle (monotonic clock):

* ``open``   — traffic seen within ``stale_after``.
* ``stale``  — silent longer than ``stale_after``: the device is treated as
  away; held objects are released by its consumers (see ``on_stale``).
* ``closed`` — silent longer than ``idle_timeout``, older than
  ``max_lifetime``, revoked, replaced or closed by the client. A closed session
  never reopens; the device performs a new handshake.

Each session has an ``Outbox``: server messages carry a monotonic (not
contiguous) ``sseq``. A client resumes after a short disconnect by asking for
messages after the last ``sseq`` it processed; when the retained window no
longer covers that point it receives ``resync_required`` and re-reads state.
Lossy messages (previews, presence) may carry a coalescing key so a slow link
receives only the newest one.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, FrozenSet, List, Optional, Tuple

from app.remote.capabilities import Capability
from app.remote.flow import RATE_CLASSES, ClockEstimator, TokenBucket

OUTBOX_RETAIN = 256
OUTBOX_MAX_PENDING = 512
RESULT_CACHE = 256


@dataclass(frozen=True)
class SessionConfig:
    heartbeat_ms: int = 5000
    stale_after: float = 12.0
    idle_timeout: float = 90.0
    max_lifetime: float = 12 * 3600.0
    max_sessions_per_device: int = 4
    max_sessions: int = 64

    def public(self) -> Dict[str, Any]:
        return {"heartbeat_ms": self.heartbeat_ms, "stale_after_ms": int(self.stale_after * 1000),
                "idle_timeout_ms": int(self.idle_timeout * 1000), "max_lifetime_ms": int(self.max_lifetime * 1000)}


class SessionAuthError(PermissionError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Outbox:
    def __init__(self) -> None:
        self.sseq = 0
        self.acked = 0
        self.floor = 0  # highest sseq dropped for good (trimmed or overflowed; not coalesced)
        self.messages: Deque[Dict[str, Any]] = deque()
        self._keys: Dict[str, int] = {}
        self._waiters: List[asyncio.Future] = []
        self._lock = threading.Lock()
        self.overflowed = 0

    def push(self, kind: str, body: Dict[str, Any], *, re: Optional[str] = None, coalesce: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            if coalesce is not None and coalesce in self._keys:
                stale = self._keys.pop(coalesce)
                if stale > self.acked:
                    self.messages = deque(m for m in self.messages if m["sseq"] != stale)
            self.sseq += 1
            message: Dict[str, Any] = {"v": 1, "sseq": self.sseq, "kind": kind, "body": body}
            if re is not None:
                message["re"] = re
            self.messages.append(message)
            if coalesce is not None:
                self._keys[coalesce] = self.sseq
            pending = sum(1 for m in self.messages if m["sseq"] > self.acked)
            if pending > OUTBOX_MAX_PENDING:
                # The client is not reading. Drop the backlog; it must re-read state.
                self.overflowed += 1
                self.floor = self.sseq
                self.messages.clear()
                self._keys.clear()
                self.sseq += 1
                message = {"v": 1, "sseq": self.sseq, "kind": "resync_required", "body": {"reason": "backlog"}}
                self.messages.append(message)
            waiters, self._waiters = self._waiters, []
        for waiter in waiters:
            _wake(waiter)
        return message

    def ack(self, upto: int) -> None:
        with self._lock:
            if upto > self.acked:
                self.acked = min(upto, self.sseq)
            while len(self.messages) > OUTBOX_RETAIN and self.messages[0]["sseq"] <= self.acked:
                self.floor = self.messages.popleft()["sseq"]

    def after(self, cursor: int, limit: int = 200) -> Tuple[List[Dict[str, Any]], bool]:
        """Messages after ``cursor``; the flag is False when the cursor fell out of the retained window."""
        with self._lock:
            if cursor > self.sseq:
                return [], False
            covered = cursor >= self.floor
            selected = [m for m in self.messages if m["sseq"] > cursor][:limit]
        return selected, covered

    async def wait(self, cursor: int, timeout: float) -> List[Dict[str, Any]]:
        messages, _ = self.after(cursor)
        if messages or timeout <= 0:
            return messages
        loop = asyncio.get_running_loop()
        waiter = loop.create_future()
        with self._lock:
            if self.sseq > cursor:
                waiter = None
            else:
                self._waiters.append(waiter)
        if waiter is not None:
            try:
                await asyncio.wait_for(waiter, timeout)
            except asyncio.TimeoutError:
                pass
            finally:
                with self._lock:
                    if waiter in self._waiters:
                        self._waiters.remove(waiter)
        messages, _ = self.after(cursor)
        return messages

    def wake_all(self) -> None:
        with self._lock:
            waiters, self._waiters = self._waiters, []
        for waiter in waiters:
            _wake(waiter)


def _wake(waiter: asyncio.Future) -> None:
    def _set() -> None:
        if not waiter.done():
            waiter.set_result(None)
    try:
        waiter.get_loop().call_soon_threadsafe(_set)
    except RuntimeError:
        pass


@dataclass
class RemoteSession:
    id: str
    kind: str  # "device" | "owner"
    device: Dict[str, Any]
    token_hash: str
    requested: Optional[FrozenSet[str]]
    scopes: FrozenSet[str]
    client: Dict[str, Any]
    capabilities: Dict[str, Capability]
    created: float
    last_seen: float
    expires_at: float
    opened_at_ms: float
    state: str = "open"
    close_reason: Optional[str] = None
    reliable_seq: int = 0
    realtime_seq: Dict[str, int] = field(default_factory=dict)
    results: "OrderedDict[str, Dict[str, Any]]" = field(default_factory=OrderedDict)
    clock: ClockEstimator = field(default_factory=ClockEstimator)
    buckets: Dict[str, TokenBucket] = field(default_factory=dict)
    outbox: Outbox = field(default_factory=Outbox)
    channels: set = field(default_factory=set)
    transport: Optional[str] = None
    stats: Dict[str, int] = field(default_factory=dict)
    data: Dict[str, Any] = field(default_factory=dict)  # consumer-owned ephemeral state

    def device_public(self) -> Dict[str, Any]:
        return {"id": self.device.get("id"), "name": self.device.get("name"), "device_type": self.device.get("device_type"),
                "kind": self.kind}

    def count(self, key: str, amount: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + amount

    def bucket(self, rate_class: str) -> TokenBucket:
        if rate_class not in self.buckets:
            rate, burst = RATE_CLASSES[rate_class]
            self.buckets[rate_class] = TokenBucket(rate, burst)
        return self.buckets[rate_class]

    def remember(self, message_id: str, response: Dict[str, Any]) -> None:
        self.results[message_id] = response
        while len(self.results) > RESULT_CACHE:
            self.results.popitem(last=False)

    def public(self, now: float) -> Dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "device": self.device_public(), "state": self.state,
            "close_reason": self.close_reason, "scopes": sorted(self.scopes), "client": dict(self.client),
            "capabilities": [c.public() for c in self.capabilities.values()], "transport": self.transport,
            "last_seen_seconds": round(now - self.last_seen, 2), "age_seconds": round(now - self.created, 1),
            "reliable_seq": self.reliable_seq, "sseq": self.outbox.sseq, "clock": self.clock.public(),
            "channels": sorted(self.channels), "stats": dict(self.stats),
        }


class SessionManager:
    def __init__(self, config: SessionConfig = SessionConfig(), monotonic: Callable[[], float] = time.monotonic,
                 wall_ms: Callable[[], float] = lambda: time.time() * 1000) -> None:
        self.config = config
        self.monotonic = monotonic
        self.wall_ms = wall_ms
        self.sessions: Dict[str, RemoteSession] = {}
        self._lock = threading.RLock()

    def open(self, kind: str, device: Dict[str, Any], scopes: FrozenSet[str], requested: Optional[FrozenSet[str]],
             client: Dict[str, Any], capabilities: Dict[str, Capability]) -> Tuple[RemoteSession, str, List[RemoteSession]]:
        now = self.monotonic()
        token = secrets.token_urlsafe(32)
        session = RemoteSession(
            id="rs-" + secrets.token_hex(8), kind=kind, device=dict(device), token_hash=_hash(token),
            requested=requested, scopes=scopes, client=dict(client), capabilities=capabilities, created=now,
            last_seen=now, expires_at=now + self.config.max_lifetime, opened_at_ms=self.wall_ms())
        replaced: List[RemoteSession] = []
        with self._lock:
            mine = sorted((s for s in self.sessions.values() if s.state != "closed" and s.device.get("id") == device.get("id")),
                          key=lambda s: s.created)
            while len(mine) >= self.config.max_sessions_per_device:
                replaced.append(mine.pop(0))
            live = sorted((s for s in self.sessions.values() if s.state != "closed"), key=lambda s: s.last_seen)
            while len(live) - len(replaced) >= self.config.max_sessions:
                victim = live.pop(0)
                if victim not in replaced:
                    replaced.append(victim)
            for victim in replaced:
                self._close_locked(victim, "replaced")
            self.sessions[session.id] = session
            self._forget_closed_locked()
        return session, token, replaced

    def get(self, session_id: str) -> RemoteSession:
        with self._lock:
            session = self.sessions.get(session_id) if isinstance(session_id, str) else None
        if session is None:
            raise SessionAuthError("session_unknown", "Unknown remote session. Open a new one with the device key.")
        return session

    def authenticate(self, session_id: str, token: Optional[str]) -> RemoteSession:
        session = self.get(session_id)
        if not isinstance(token, str) or len(token) > 256 or not hmac.compare_digest(_hash(token), session.token_hash):
            raise SessionAuthError("session_invalid", "Invalid remote session credential.")
        return self.check_live(session)

    def check_live(self, session: RemoteSession) -> RemoteSession:
        if session.state == "closed":
            code = "session_revoked" if session.close_reason == "revoked" else "session_expired"
            raise SessionAuthError(code, f"Remote session is closed ({session.close_reason}).")
        now = self.monotonic()
        if now >= session.expires_at or now - session.last_seen > self.config.idle_timeout:
            self.close(session, "expired")
            raise SessionAuthError("session_expired", "Remote session expired. Open a new one with the device key.")
        return session

    def touch(self, session: RemoteSession) -> bool:
        """Record traffic. Returns True when a stale session came back."""
        session.last_seen = self.monotonic()
        if session.state == "stale":
            session.state = "open"
            return True
        return False

    def close(self, session: RemoteSession, reason: str) -> bool:
        with self._lock:
            return self._close_locked(session, reason)

    def _close_locked(self, session: RemoteSession, reason: str) -> bool:
        if session.state == "closed":
            return False
        session.state = "closed"
        session.close_reason = reason
        session.outbox.push("session.closed", {"reason": reason})
        return True

    def _forget_closed_locked(self) -> None:
        closed = [s for s in self.sessions.values() if s.state == "closed"]
        if len(closed) > 256:
            for session in sorted(closed, key=lambda s: s.last_seen)[: len(closed) - 256]:
                del self.sessions[session.id]

    def sweep(self) -> List[Tuple[RemoteSession, str]]:
        """Apply timeouts. Returns (session, transition) pairs: 'stale' or 'closed'."""
        now = self.monotonic()
        changes: List[Tuple[RemoteSession, str]] = []
        with self._lock:
            for session in list(self.sessions.values()):
                if session.state == "closed":
                    continue
                silent = now - session.last_seen
                if now >= session.expires_at:
                    self._close_locked(session, "lifetime")
                    changes.append((session, "closed"))
                elif silent > self.config.idle_timeout:
                    self._close_locked(session, "idle")
                    changes.append((session, "closed"))
                elif silent > self.config.stale_after and session.state == "open":
                    session.state = "stale"
                    changes.append((session, "stale"))
            self._forget_closed_locked()
        return changes

    def live(self) -> List[RemoteSession]:
        with self._lock:
            return [s for s in self.sessions.values() if s.state != "closed"]

    def for_device(self, device_id: str) -> List[RemoteSession]:
        return [s for s in self.live() if s.device.get("id") == device_id]
