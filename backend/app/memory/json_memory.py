import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Literal, Optional, cast

from app.core.config import get_settings
from app.core.intent import Intent
from app.memory.base import MemoryMessage, MemoryStore


class JSONMemory(MemoryStore):
    """Small file-backed memory store suitable for local development."""

    def __init__(
        self,
        file_path: Path,
        history_limit: Optional[int] = None,
    ) -> None:
        self.file_path = file_path
        self.history_limit = history_limit or get_settings().memory_history_limit
        self._lock = Lock()
        self._ensure_file()

    def _ensure_file(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self.file_path.write_text(
                json.dumps({"conversations": {}}, indent=2),
                encoding="utf-8",
            )

    def _read(self) -> dict[str, object]:
        try:
            data = cast(
                dict[str, object],
                json.loads(self.file_path.read_text(encoding="utf-8")),
            )
            self._normalize_legacy_entries(data)
            return data
        except (json.JSONDecodeError, OSError):
            return {"conversations": {}}

    @staticmethod
    def _normalize_legacy_entries(data: dict[str, object]) -> None:
        conversations = cast(
            dict[str, list[dict[str, object]]],
            data.setdefault("conversations", {}),
        )
        for history in conversations.values():
            for entry in history:
                if "timestamp" not in entry:
                    entry["timestamp"] = entry.pop(
                        "created_at",
                        datetime.now(timezone.utc).isoformat(),
                    )
                entry.setdefault("intent", None)

    def _write(self, data: dict[str, object]) -> None:
        temporary_file = self.file_path.with_suffix(".tmp")
        temporary_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_file.replace(self.file_path)

    def get_history(self, session_id: str) -> list[MemoryMessage]:
        with self._lock:
            data = self._read()
            conversations = cast(
                dict[str, list[MemoryMessage]],
                data.setdefault("conversations", {}),
            )
            return list(conversations.get(session_id, []))[-self.history_limit:]

    def append(
        self,
        session_id: str,
        role: Literal["user", "assistant"],
        content: str,
        intent: Optional[Intent] = None,
    ) -> None:
        message: MemoryMessage = {
            "role": role,
            "content": content,
            "intent": intent,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            data = self._read()
            conversations = cast(
                dict[str, list[MemoryMessage]],
                data.setdefault("conversations", {}),
            )
            history = conversations.setdefault(session_id, [])
            history.append(message)
            conversations[session_id] = history[-self.history_limit:]
            self._write(data)

    def clear(self, session_id: str) -> None:
        with self._lock:
            data = self._read()
            conversations = cast(
                dict[str, list[MemoryMessage]],
                data.setdefault("conversations", {}),
            )
            conversations.pop(session_id, None)
            self._write(data)
