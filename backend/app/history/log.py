"""Hash-chained, append-only action log with crash-safe JSONL persistence.

Layout of a persisted stream directory::

    header.json    immutable stream header (domain, version, initial state)
    events.jsonl   one canonical JSON event per line

Every event stores ``prev_hash`` (the previous event's hash, or the header
digest for the first event) and its own ``hash``. Opening a stream recomputes
the chain; any edited, reordered, duplicated or truncated-in-the-middle line
raises ``LogCorrupted``. A final line without its newline terminator can only
come from a crash during ``append`` before the write was acknowledged (the
writer fsyncs the complete line before returning), so it is dropped and the
stream reports ``torn_tail_recovered``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.history.canonical import canonical_json, digest

HEADER_SCHEMA = "akashi.action-stream/1"
EVENT_SCHEMA = "akashi.action-event/1"


class LogCorrupted(RuntimeError):
    def __init__(self, reason: str, line: Optional[int] = None) -> None:
        self.reason = reason
        self.line = line
        super().__init__(f"Action log corrupted{f' at line {line}' if line else ''}: {reason}")


def event_hash(event: Dict[str, Any]) -> str:
    return digest({key: value for key, value in event.items() if key != "hash"})


class ActionLog:
    def __init__(self, header: Dict[str, Any], directory: Optional[Path] = None,
                 events: Optional[List[Dict[str, Any]]] = None, torn_tail_recovered: bool = False) -> None:
        if header.get("schema") != HEADER_SCHEMA:
            raise LogCorrupted("Unsupported stream header schema.")
        self.header = header
        self.directory = directory
        self.events: List[Dict[str, Any]] = list(events or [])
        self.torn_tail_recovered = torn_tail_recovered
        self.genesis = digest(header)

    # Construction -----------------------------------------------------------------
    @classmethod
    def create(cls, header: Dict[str, Any], directory: Optional[Path] = None) -> "ActionLog":
        header = {"schema": HEADER_SCHEMA, **header}
        if directory is not None:
            directory.mkdir(parents=True, exist_ok=False)
            temporary = directory / "header.json.tmp"
            temporary.write_text(canonical_json(header), encoding="utf-8")
            temporary.replace(directory / "header.json")
            (directory / "events.jsonl").touch()
        return cls(header, directory)

    @classmethod
    def open(cls, directory: Path) -> "ActionLog":
        try:
            header = json.loads((directory / "header.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LogCorrupted("Stream header is missing or unreadable.") from exc
        if not isinstance(header, dict):
            raise LogCorrupted("Stream header is not an object.")
        log = cls(header, directory)
        try:
            raw = (directory / "events.jsonl").read_bytes()
        except OSError as exc:
            raise LogCorrupted("Event file is missing or unreadable.") from exc
        torn = False
        if raw and not raw.endswith(b"\n"):
            cut = raw.rfind(b"\n")
            raw = raw[: cut + 1] if cut >= 0 else b""
            torn = True
        events = []
        for number, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise LogCorrupted("Event line is not valid JSON.", number) from exc
            events.append(event)
        log.events = []
        for number, event in enumerate(events, start=1):
            log._verify_next(event, number)
            log.events.append(event)
        if torn:
            log._rewrite()
        log.torn_tail_recovered = torn
        return log

    # Integrity --------------------------------------------------------------------
    @property
    def head(self) -> str:
        return self.events[-1]["hash"] if self.events else self.genesis

    def _verify_next(self, event: Any, line: int) -> None:
        if not isinstance(event, dict):
            raise LogCorrupted("Event is not an object.", line)
        if event.get("schema") != EVENT_SCHEMA:
            raise LogCorrupted("Unsupported event schema.", line)
        expected_seq = len(self.events) + 1
        if event.get("seq") != expected_seq:
            raise LogCorrupted(f"Expected sequence {expected_seq}.", line)
        if event.get("prev_hash") != self.head:
            raise LogCorrupted("Hash chain is broken.", line)
        if event.get("hash") != event_hash(event):
            raise LogCorrupted("Event content does not match its hash.", line)

    def verify(self) -> None:
        events, self.events = self.events, []
        try:
            for number, event in enumerate(events, start=1):
                self._verify_next(event, number)
                self.events.append(event)
        except LogCorrupted:
            self.events = events
            raise

    # Writing ----------------------------------------------------------------------
    def append(self, event: Dict[str, Any]) -> Dict[str, Any]:
        event = {**event, "schema": EVENT_SCHEMA, "seq": len(self.events) + 1, "prev_hash": self.head}
        event.pop("hash", None)
        event["hash"] = event_hash(event)
        line = canonical_json(event) + "\n"
        if self.directory is not None:
            with (self.directory / "events.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())
        self.events.append(event)
        return event

    def _rewrite(self) -> None:
        if self.directory is None:
            return
        temporary = self.directory / "events.jsonl.tmp"
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            for event in self.events:
                stream.write(canonical_json(event) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.directory / "events.jsonl")
