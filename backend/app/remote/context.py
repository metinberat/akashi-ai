"""Request-scoped remote context for code paths shared with local input.

When a remote device's utterance runs through AKASHI's normal chat pipeline,
this context carries the device's scopes and provenance so that live actions
are limited to the ones a remote device may trigger and scene changes are
recorded with remote provenance.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Dict, Optional

# Live actions a remote device may trigger through chat. Computer-control
# actions (applications, desktop, browser, files, autonomy) are never included.
REMOTE_LIVE_ACTIONS = frozenset({"spatial.scene", "remote.devices"})

_current: ContextVar[Optional[Dict[str, Any]]] = ContextVar("akashi_remote_context", default=None)


def current() -> Optional[Dict[str, Any]]:
    return _current.get()


def enter(context: Dict[str, Any]):
    return _current.set(context)


def leave(token) -> None:
    _current.reset(token)


def live_action_allowed(name: str) -> bool:
    return _current.get() is None or name in REMOTE_LIVE_ACTIONS
