from __future__ import annotations

import json
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List


def _tokens(value: str) -> set[str]:
    return {item for item in re.findall(r"[a-z0-9çğıöşü_-]{3,}", value.casefold())}


class SkillLibrary:
    """Verified workflow knowledge, not executable macros or source code."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            self._write({"version": 1, "skills": []})

    def _read(self) -> Dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or not isinstance(value.get("skills"), list):
                raise ValueError("invalid skill store")
            return value
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("Skill library is unreadable; it was not overwritten.") from exc

    def _write(self, value: Dict[str, Any]) -> None:
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def add_candidate(self, task: Dict[str, Any]) -> Dict[str, Any]:
        completed = [node for node in task.get("subgoals", []) if node.get("status") == "completed"]
        item = {
            "id": f"skill-{uuid.uuid4().hex[:16]}",
            "name": str(task.get("title") or task.get("goal") or "Workflow")[:160],
            "problem_type": str(task.get("goal") or "")[:1000],
            "status": "candidate",
            "preconditions": sorted({str(node.get("channel") or "computer") for node in completed}),
            "applications": sorted({str(entity.get("value")) for entity in task.get("entities", {}).values() if isinstance(entity, dict) and entity.get("kind") == "application"}),
            "workflow": [str(node.get("title") or "")[:300] for node in completed],
            "success_criteria": [str(node.get("acceptance") or "")[:500] for node in completed],
            "failure_modes": [str(event.get("summary") or "")[:300] for event in task.get("events", []) if event.get("kind") in {"error", "retry", "replan"}][-20:],
            "source_task_id": task.get("id"),
            "provenance": deepcopy(task.get("skill_provenance", {})),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            data = self._read()
            data["skills"].append(item)
            data["skills"] = data["skills"][-300:]
            self._write(data)
        return deepcopy(item)

    def activate(self, skill_id: str) -> Dict[str, Any]:
        with self._lock:
            data = self._read()
            item = next((skill for skill in data["skills"] if skill.get("id") == skill_id), None)
            if item is None:
                raise KeyError("Skill was not found.")
            item["status"] = "active"
            self._write(data)
            return deepcopy(item)

    def search(self, query: str, limit: int = 5, include_candidates: bool = True) -> List[Dict[str, Any]]:
        query_tokens = _tokens(query)
        with self._lock:
            skills = list(self._read()["skills"])
        scored = []
        for item in skills:
            if item.get("status") != "active" and not include_candidates:
                continue
            text = json.dumps(item, ensure_ascii=False)
            overlap = len(query_tokens.intersection(_tokens(text)))
            if overlap:
                scored.append((overlap, item.get("created_at", ""), item))
        scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
        return deepcopy([item for _, _, item in scored[: max(1, min(limit, 20))]])

    def list(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            return deepcopy(list(reversed(self._read()["skills"][-max(1, min(limit, 300)):])))
