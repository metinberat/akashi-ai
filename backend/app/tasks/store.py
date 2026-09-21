import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, cast


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JSONTaskStore:
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self._lock = Lock()
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self.file_path.write_text(
                json.dumps({"version": 1, "tasks": []}, indent=2),
                encoding="utf-8",
            )
        self.recover_interrupted()

    def _read(self) -> Dict[str, Any]:
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("tasks", []), list):
                raise ValueError("Invalid task store")
            return cast(Dict[str, Any], data)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Task store at '{self.file_path}' is unreadable; it was not overwritten."
            ) from exc

    def _write(self, data: Dict[str, Any]) -> None:
        temporary = self.file_path.with_suffix(f"{self.file_path.suffix}.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.file_path)

    def recover_interrupted(self) -> None:
        with self._lock:
            data = self._read()
            changed = False
            for task in data.get("tasks", []):
                if task.get("status") in {"queued", "planning", "running"}:
                    task["status"] = "failed"
                    task["error"] = "Backend restarted while this task was running."
                    task["updated_at"] = utc_now()
                    changed = True
            if changed:
                self._write(data)

    def create(self, task: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            data = self._read()
            data.setdefault("tasks", []).append(deepcopy(task))
            self._write(data)
        return deepcopy(task)

    def list(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            tasks = list(self._read().get("tasks", []))
        tasks.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return deepcopy(tasks[: max(1, min(limit, 500))])

    def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            found = next(
                (item for item in self._read().get("tasks", []) if item.get("id") == task_id),
                None,
            )
        return deepcopy(found) if found else None

    def replace(self, task: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            data = self._read()
            tasks = data.get("tasks", [])
            for index, current in enumerate(tasks):
                if current.get("id") == task.get("id"):
                    tasks[index] = deepcopy(task)
                    self._write(data)
                    return deepcopy(task)
        raise KeyError("Task was not found.")
