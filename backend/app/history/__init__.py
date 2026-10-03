"""Reusable action-history foundation (events, patches, undo/redo, replay).

Spatial Lab is the first domain built on it. Other AKASHI domains (task replay,
computer-agent audit, FORM workflows) can adopt it by supplying a pure domain
``apply`` function; see ``docs/spatial-lab.md`` for the event contract.
"""

from app.history.canonical import canonical_json, digest, quantize
from app.history.engine import (
    ActionHistory,
    CommandRejected,
    DomainResult,
    HistoryConflict,
    HistoryFull,
    ReplayDivergence,
    ReplayReport,
)
from app.history.log import ActionLog, LogCorrupted

__all__ = [
    "ActionHistory", "ActionLog", "CommandRejected", "DomainResult", "HistoryConflict",
    "HistoryFull", "LogCorrupted", "ReplayDivergence", "ReplayReport", "canonical_json",
    "digest", "quantize",
]
