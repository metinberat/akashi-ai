"""Domain-agnostic command history: execute, undo, redo, restore and replay.

A *domain* supplies a pure ``apply(state, command)`` that validates a command
and returns the next state. ``ActionHistory`` turns each accepted command into
an append-only event that records what changed (reversible patches), the state
digests before and after, the origin of the input and the original request.

Undo and redo are themselves events, so the log is never rewritten and a full
session can be replayed, audited or reconstructed at any sequence number.

Two reconstruction paths exist on purpose:

* ``restore`` re-applies recorded patches and checks every recorded digest. It
  detects storage corruption and does not depend on today's domain code.
* ``verify_replay`` re-executes every recorded command with today's domain code
  from the initial state and requires identical patches and digests. It proves
  the domain is deterministic and that the log is a faithful history.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Protocol

from app.history.canonical import digest
from app.history.log import ActionLog, LogCorrupted
from app.history import patch as patches


class CommandRejected(ValueError):
    """A command failed domain validation; nothing was changed."""

    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        self.code = code
        self.details = details or {}
        super().__init__(message)


class HistoryConflict(RuntimeError):
    """Undo/redo could not be applied because the state diverged from the log."""


class HistoryFull(RuntimeError):
    pass


class ReplayDivergence(RuntimeError):
    def __init__(self, seq: int, reason: str) -> None:
        self.seq = seq
        self.reason = reason
        super().__init__(f"Replay diverged at event {seq}: {reason}")


@dataclass
class DomainResult:
    state: Dict[str, Any]
    category: str
    undoable: bool
    targets: List[str] = field(default_factory=list)
    summary: str = ""


class Domain(Protocol):
    name: str
    version: str

    def apply(self, state: Dict[str, Any], command: Dict[str, Any]) -> DomainResult: ...

    def reconcile(self, state: Dict[str, Any]) -> Dict[str, Any]: ...


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ReplayReport:
    verified: bool
    events: int
    final_digest: str
    commands: int
    undos: int
    redos: int


class ActionHistory:
    def __init__(self, domain: Domain, log: ActionLog, *, max_events: int = 10_000,
                 clock: Callable[[], str] = utc_now,
                 ids: Callable[[], str] = lambda: uuid.uuid4().hex) -> None:
        header = log.header
        if header.get("domain") != domain.name:
            raise LogCorrupted("Stream belongs to a different domain.")
        self.domain = domain
        self.log = log
        self.max_events = max_events
        self.clock = clock
        self.ids = ids
        self.initial_state: Dict[str, Any] = copy.deepcopy(header["initial_state"])
        self.state: Dict[str, Any] = copy.deepcopy(self.initial_state)
        self.undo_stack: List[int] = []
        self.redo_stack: List[int] = []

    # Construction -----------------------------------------------------------------
    @classmethod
    def create(cls, domain: Domain, stream_id: str, initial_state: Dict[str, Any], *,
               directory=None, metadata: Optional[Dict[str, Any]] = None, **options: Any) -> "ActionHistory":
        header = {
            "stream": stream_id,
            "domain": domain.name,
            "domain_version": domain.version,
            "created_at": options.get("clock", utc_now)(),
            "initial_state": copy.deepcopy(initial_state),
            "initial_digest": digest(initial_state),
            "metadata": metadata or {},
        }
        return cls(domain, ActionLog.create(header, directory), **options)

    @classmethod
    def restore(cls, domain: Domain, log: ActionLog, **options: Any) -> "ActionHistory":
        """Rebuild from recorded patches, verifying every digest along the way."""
        history = cls(domain, log, **options)
        if digest(history.initial_state) != log.header.get("initial_digest"):
            raise LogCorrupted("Initial state does not match its digest.")
        for event in log.events:
            if event.get("digest_before") != digest(history.state):
                raise LogCorrupted("State before event does not match the record.", event.get("seq"))
            try:
                history.state = patches.apply(history.state, event.get("patches", []))
            except patches.PatchConflict as exc:
                raise LogCorrupted(f"Recorded patch does not apply: {exc}", event.get("seq")) from exc
            if event.get("digest_after") != digest(history.state):
                raise LogCorrupted("State after event does not match the record.", event.get("seq"))
            history._track_stacks(event)
        return history

    # Properties -------------------------------------------------------------------
    @property
    def stream_id(self) -> str:
        return self.log.header["stream"]

    @property
    def revision(self) -> int:
        return len(self.log.events)

    @property
    def events(self) -> List[Dict[str, Any]]:
        return self.log.events

    def can_undo(self) -> bool:
        return bool(self.undo_stack)

    def can_redo(self) -> bool:
        return bool(self.redo_stack)

    def digest(self) -> str:
        return digest(self.state)

    # Mutation ---------------------------------------------------------------------
    def execute(self, command: Dict[str, Any], origin: Dict[str, Any],
                request: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Apply one validated command. Returns the event, or None for a no-op."""
        self._require_capacity()
        result = self.domain.apply(copy.deepcopy(self.state), copy.deepcopy(command))
        changes = patches.diff(self.state, result.state)
        if not changes:
            return None
        event = self._record("command", command, origin, request, result.category, result.undoable,
                             result.targets, result.summary, changes, result.state)
        if result.undoable:
            self.undo_stack.append(event["seq"])
            self.redo_stack.clear()
        return event

    def undo(self, origin: Dict[str, Any], request: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.undo_stack:
            raise CommandRejected("nothing_to_undo", "There is nothing to undo.")
        self._require_capacity()
        target = self.log.events[self.undo_stack[-1] - 1]
        next_state = self._patched(patches.invert(target["patches"]), target["seq"])
        event = self._record("undo", {"type": "history.undo"}, origin, request, target["category"], False,
                             target["targets"], "Undo: " + target.get("summary", ""),
                             patches.diff(self.state, next_state), next_state, undoes=target["seq"])
        self.redo_stack.append(self.undo_stack.pop())
        return event

    def redo(self, origin: Dict[str, Any], request: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.redo_stack:
            raise CommandRejected("nothing_to_redo", "There is nothing to redo.")
        self._require_capacity()
        target = self.log.events[self.redo_stack[-1] - 1]
        next_state = self._patched(target["patches"], target["seq"])
        event = self._record("redo", {"type": "history.redo"}, origin, request, target["category"], False,
                             target["targets"], "Redo: " + target.get("summary", ""),
                             patches.diff(self.state, next_state), next_state, redoes=target["seq"])
        self.undo_stack.append(self.redo_stack.pop())
        return event

    # Reconstruction ---------------------------------------------------------------
    def state_at(self, seq: int) -> Dict[str, Any]:
        if not 0 <= seq <= self.revision:
            raise ValueError("Sequence is outside this history.")
        state = copy.deepcopy(self.initial_state)
        for event in self.log.events[:seq]:
            state = patches.apply(state, event["patches"])
        return state

    def verify_replay(self) -> ReplayReport:
        """Re-execute every event with the current domain code and compare."""
        replica = ActionHistory.create(self.domain, self.stream_id + ":replay", self.initial_state,
                                       max_events=self.max_events + 1)
        counts = {"command": 0, "undo": 0, "redo": 0}
        for event in self.log.events:
            kind = event.get("kind")
            try:
                if kind == "command":
                    produced = replica.execute(event["command"], event.get("origin", {}), event.get("request"))
                elif kind == "undo":
                    produced = replica.undo(event.get("origin", {}))
                elif kind == "redo":
                    produced = replica.redo(event.get("origin", {}))
                else:
                    raise ReplayDivergence(event.get("seq", 0), f"Unknown event kind {kind!r}.")
            except (CommandRejected, HistoryConflict) as exc:
                raise ReplayDivergence(event["seq"], f"Re-execution rejected: {exc}") from exc
            if produced is None:
                raise ReplayDivergence(event["seq"], "Re-execution produced no change.")
            for key in ("patches", "digest_before", "digest_after", "undoes", "redoes", "category", "targets"):
                if produced.get(key) != event.get(key):
                    raise ReplayDivergence(event["seq"], f"Field {key!r} differs.")
            counts[kind] += 1
        return ReplayReport(True, len(self.log.events), replica.digest(), counts["command"], counts["undo"], counts["redo"])

    # Internals --------------------------------------------------------------------
    def _require_capacity(self) -> None:
        if self.revision >= self.max_events:
            raise HistoryFull("This history reached its event budget; start a new session.")

    def _patched(self, changes: List[Dict[str, Any]], seq: int) -> Dict[str, Any]:
        try:
            state = patches.apply(self.state, changes)
        except patches.PatchConflict as exc:
            raise HistoryConflict(f"Event {seq} no longer applies: {exc}") from exc
        return self.domain.reconcile(state)

    def _record(self, kind: str, command: Dict[str, Any], origin: Dict[str, Any], request: Optional[Dict[str, Any]],
                category: str, undoable: bool, targets: List[str], summary: str,
                changes: List[Dict[str, Any]], next_state: Dict[str, Any], *,
                undoes: Optional[int] = None, redoes: Optional[int] = None) -> Dict[str, Any]:
        event = self.log.append({
            "stream": self.stream_id,
            "domain": self.domain.name,
            "domain_version": self.domain.version,
            "id": self.ids(),
            "at": self.clock(),
            "kind": kind,
            "origin": copy.deepcopy(origin),
            "request": copy.deepcopy(request),
            "command": copy.deepcopy(command),
            "category": category,
            "undoable": undoable,
            "targets": list(targets),
            "summary": summary[:300],
            "undoes": undoes,
            "redoes": redoes,
            "patches": changes,
            "digest_before": digest(self.state),
            "digest_after": digest(next_state),
        })
        self.state = next_state
        return event

    def _track_stacks(self, event: Dict[str, Any]) -> None:
        kind = event.get("kind")
        if kind == "command" and event.get("undoable"):
            self.undo_stack.append(event["seq"])
            self.redo_stack.clear()
        elif kind == "undo":
            if not self.undo_stack or self.undo_stack[-1] != event.get("undoes"):
                raise LogCorrupted("Undo event does not match the undo stack.", event.get("seq"))
            self.redo_stack.append(self.undo_stack.pop())
        elif kind == "redo":
            if not self.redo_stack or self.redo_stack[-1] != event.get("redoes"):
                raise LogCorrupted("Redo event does not match the redo stack.", event.get("seq"))
            self.undo_stack.append(self.redo_stack.pop())
