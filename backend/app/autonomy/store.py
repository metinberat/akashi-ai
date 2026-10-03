from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JSONAutonomyStore:
    """Atomic checkpoints for long-running goals; payloads stay metadata-only."""

    def __init__(self, path: Path, limit: int = 100) -> None:
        self.path = path
        self.limit = max(10, min(limit, 500))
        self._lock = Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({"version": 2, "tasks": {}})
        self.recover_interrupted()

    def _read(self) -> Dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or not isinstance(value.get("tasks"), dict):
                raise ValueError("invalid autonomy store")
            return value
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("Autonomy state is unreadable; it was not overwritten.") from exc

    def _write(self, value: Dict[str, Any]) -> None:
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def recover_interrupted(self) -> None:
        with self._lock:
            data = self._read()
            changed = False
            for task in data["tasks"].values():
                if task.get("status") in {"queued", "planning", "running", "evaluating", "replanning"}:
                    task["status"] = "paused_recovery"
                    task["recovery_reason"] = "Core restarted; resume from the last verified checkpoint."
                    task["updated_at"] = utc_now()
                    for node in task.get("subgoals", []):
                        if node.get("status") in {"running", "evaluating"}:
                            node["status"] = "pending"
                            node["error"] = "Interrupted by Core restart; outcome not assumed."
                    changed = True
            if changed:
                self._write(data)

    def create(self, task: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            data = self._read()
            data["tasks"][task["id"]] = deepcopy(task)
            if len(data["tasks"]) > self.limit:
                oldest = sorted((key for key in data["tasks"] if data["tasks"][key].get("status") in {"completed", "cancelled", "failed"}), key=lambda key: data["tasks"][key].get("updated_at", ""))
                if len(oldest) < len(data["tasks"]) - self.limit:
                    raise ValueError("Active autonomy task capacity reached; finish or cancel existing tasks.")
                for key in oldest[: len(data["tasks"]) - self.limit]:
                    data["tasks"].pop(key, None)
            self._write(data)
        return deepcopy(task)

    def replace(self, task: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            data = self._read()
            if task.get("id") not in data["tasks"]:
                raise KeyError("Autonomy task was not found.")
            task["updated_at"] = utc_now()
            task["revision"] = int(task.get("revision", 0)) + 1
            task["events"] = list(task.get("events") or [])[-500:]
            task["artifacts"] = list(task.get("artifacts") or [])[-200:]
            data["tasks"][task["id"]] = deepcopy(task)
            self._write(data)
        return deepcopy(task)

    def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            value = self._read()["tasks"].get(task_id)
            return deepcopy(value) if isinstance(value, dict) else None

    def list(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            values = list(self._read()["tasks"].values())
        values.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return deepcopy(values[: max(1, min(limit, 200))])
