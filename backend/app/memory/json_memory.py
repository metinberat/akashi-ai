import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Literal, Optional, cast

from app.core.config import get_settings
from app.core.intent import Intent
from app.memory.base import ConversationSummary, MemoryMessage, MemoryStore
from app.memory.long_term import safe_memory_text


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
                json.dumps({"conversations": {}, "summaries": {}}, indent=2),
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
        except (json.JSONDecodeError, OSError, TypeError) as exc:
            raise RuntimeError(
                f"Conversation memory at '{self.file_path}' is unreadable; it was not overwritten."
            ) from exc

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
        data.setdefault("summaries", {})

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
            return [dict(item, content=safe_memory_text(item["content"])) for item in conversations.get(session_id, [])[-self.history_limit:]]

    def append(
        self,
        session_id: str,
        role: Literal["user", "assistant"],
        content: str,
        intent: Optional[Intent] = None,
    ) -> None:
        message: MemoryMessage = {
            "role": role,
            "content": safe_memory_text(content),
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
            overflow = history[:-self.history_limit]
            if overflow:
                summaries = cast(
                    dict[str, str],
                    data.setdefault("summaries", {}),
                )
                existing = summaries.get(session_id, "")
                compressed = self._compress_entries(overflow)
                combined = "\n".join(
                    item for item in (existing, compressed) if item
                )
                summaries[session_id] = combined[
                    -get_settings().memory_summary_max_chars:
                ]
            conversations[session_id] = history[-self.history_limit:]
            self._write(data)

    @staticmethod
    def _compress_entries(entries: list[MemoryMessage]) -> str:
        """Create a bounded, provider-independent transcript summary."""
        lines = []
        for entry in entries:
            content = " ".join(safe_memory_text(entry.get("content", "")).split())
            if len(content) > 240:
                content = f"{content[:237]}..."
            if content:
                lines.append(f"{entry.get('role', 'unknown')}: {content}")
        return "\n".join(lines)

    def get_summary(self, session_id: str) -> Optional[str]:
        with self._lock:
            data = self._read()
            summaries = cast(dict[str, str], data.setdefault("summaries", {}))
            summary = summaries.get(session_id, "").strip()
            return safe_memory_text(summary) if summary else None

    def clear(self, session_id: str) -> None:
        with self._lock:
            data = self._read()
            conversations = cast(
                dict[str, list[MemoryMessage]],
                data.setdefault("conversations", {}),
            )
            conversations.pop(session_id, None)
            summaries = cast(
                dict[str, str],
                data.setdefault("summaries", {}),
            )
            summaries.pop(session_id, None)
            self._write(data)

    def list_conversations(self, limit: int = 30) -> list[ConversationSummary]:
        bounded_limit = max(1, min(limit, 100))
        with self._lock:
            data = self._read()
            conversations = cast(
                dict[str, list[MemoryMessage]],
                data.setdefault("conversations", {}),
            )
            summaries: list[ConversationSummary] = []
            for session_id, history in conversations.items():
                if not history:
                    continue
                first_user = next(
                    (item for item in history if item.get("role") == "user"),
                    history[0],
                )
                title = " ".join(
                    safe_memory_text(first_user.get("content", "")).split()
                )
                excerpt = " ".join(
                    safe_memory_text(history[-1].get("content", "")).split()
                )
                summaries.append({
                    "session_id": session_id,
                    "title": (title[:77] + "...") if len(title) > 80 else title,
                    "excerpt": (excerpt[:157] + "...") if len(excerpt) > 160 else excerpt,
                    "message_count": len(history),
                    "last_updated": str(history[-1].get("timestamp") or ""),
                })
            summaries.sort(key=lambda item: item["last_updated"], reverse=True)
            return summaries[:bounded_limit]
