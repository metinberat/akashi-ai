from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JSONComputerStateStore:
    """Durable, bounded computer context; never stores screenshots or secrets."""

    def __init__(self, path: Path, limit: int = 100) -> None:
        self.path = path
        self.limit = max(10, min(limit, 500))
        self._lock = Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({"version": 1, "sessions": {}})

    def _read(self) -> Dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or not isinstance(value.get("sessions"), dict):
                raise ValueError("invalid document")
            return value
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("Computer state is unreadable; it was not overwritten.") from exc

    def _write(self, value: Dict[str, Any]) -> None:
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def begin(self, task_id: str, session_id: str, goal: str) -> Dict[str, Any]:
        item = {
            "task_id": task_id,
            "session_id": session_id,
            "goal": goal[:1000],
            "status": "running",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "steps": [],
            "context": {},
        }
        with self._lock:
            data = self._read()
            sessions = data["sessions"]
            sessions[session_id] = item
            if len(sessions) > self.limit:
                oldest = sorted(sessions, key=lambda key: sessions[key].get("updated_at", ""))
                for key in oldest[: len(sessions) - self.limit]:
                    sessions.pop(key, None)
            self._write(data)
        return deepcopy(item)

    def update(
        self,
        session_id: str,
        *,
        status: Optional[str] = None,
        step: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        summary: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            data = self._read()
            item = data["sessions"].get(session_id)
            if not isinstance(item, dict):
                raise KeyError("Computer session was not found.")
            if status:
                item["status"] = status
            if step:
                item.setdefault("steps", []).append(deepcopy(step))
                item["steps"] = item["steps"][-30:]
            if context is not None:
                item["context"] = deepcopy(context)
            if summary is not None:
                item["summary"] = summary[:2000]
            item["updated_at"] = utc_now()
            self._write(data)
            return deepcopy(item)

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            item = self._read()["sessions"].get(session_id)
            return deepcopy(item) if isinstance(item, dict) else None

    def list(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            values = list(self._read()["sessions"].values())
        values.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return deepcopy(values[: max(1, min(limit, 200))])
