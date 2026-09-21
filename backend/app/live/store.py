"""Bounded durable metadata for LIVE interactions.

The store intentionally excludes prompts, model output, tool arguments, media,
and credentials. It exists to make execution state honest across a Core restart,
not to duplicate conversation memory.
"""

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JSONInteractionStore:
    def __init__(self, file_path: Optional[Path] = None, limit: int = 200) -> None:
        self.file_path = file_path
        self.limit = max(20, min(limit, 1_000))
        self._lock = Lock()
        self._memory: Dict[str, Any] = {"version": 1, "interactions": []}
        if self.file_path is not None:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            if not self.file_path.exists():
                self._write(self._memory)
            self._memory = self._read()

    def _read(self) -> Dict[str, Any]:
        if self.file_path is None:
            return deepcopy(self._memory)
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(
                data.get("interactions"), list
            ):
                raise ValueError("Invalid LIVE interaction document")
            return data
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "LIVE state is unreadable; it was not overwritten."
            ) from exc

    def _write(self, data: Dict[str, Any]) -> None:
        data["interactions"] = data.get("interactions", [])[-self.limit :]
        self._memory = deepcopy(data)
        if self.file_path is None:
            return
        temporary = self.file_path.with_suffix(f"{self.file_path.suffix}.tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.file_path)

    def recover_interrupted(self) -> None:
        with self._lock:
            data = self._read()
            changed = False
            for item in data["interactions"]:
                if item.get("status") == "running":
                    item["status"] = "interrupted_by_restart"
                    item["summary"] = "Core restarted before completion."
                    item["updated_at"] = _now()
                    changed = True
            if changed:
                self._write(data)

    def start(self, interaction_id: str, session_id: str) -> Dict[str, Any]:
        now = _now()
        item = {
            "interaction_id": interaction_id,
            "session_id": session_id[:128],
            "status": "running",
            "action": None,
            "summary": None,
            "started_at": now,
            "updated_at": now,
        }
        with self._lock:
            data = self._read()
            data["interactions"] = [
                value
                for value in data["interactions"]
                if value.get("interaction_id") != interaction_id
            ]
            data["interactions"].append(item)
            self._write(data)
        return deepcopy(item)

    def update(
        self,
        interaction_id: str,
        status: Optional[str] = None,
        action: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            data = self._read()
            item = next(
                (
                    value
                    for value in data["interactions"]
                    if value.get("interaction_id") == interaction_id
                ),
                None,
            )
            if item is None:
                return None
            if status is not None:
                item["status"] = status[:64]
            if action is not None:
                item["action"] = action[:128]
            if summary is not None:
                item["summary"] = summary[:500]
            item["updated_at"] = _now()
            self._write(data)
            return deepcopy(item)

    def get(self, interaction_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            item = next(
                (
                    value
                    for value in reversed(self._read()["interactions"])
                    if value.get("interaction_id") == interaction_id
                ),
                None,
            )
            return deepcopy(item) if item is not None else None

    def list(self, limit: int = 50) -> List[Dict[str, Any]]:
        bounded = max(1, min(limit, 200))
        with self._lock:
            items = self._read()["interactions"][-bounded:]
            return deepcopy(list(reversed(items)))
