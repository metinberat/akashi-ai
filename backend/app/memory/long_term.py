"""Durable, relevance-retrieved memory for AKASHI.

Conversation transcripts remain in ``memory.json``. This store is intentionally
separate and only contains information a user explicitly chooses to retain.
"""

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Sequence, cast

from typing_extensions import TypedDict


class LongTermMemoryEntry(TypedDict):
    id: str
    content: str
    category: str
    created_at: str
    updated_at: str
    source: str
    confidence: float
    tags: List[str]


class SensitiveMemoryError(ValueError):
    """Raised when text appears to contain credentials or private key data."""


SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.I),
    re.compile(r"\b(?:api[_ -]?key|password|passwd|secret|access[_ -]?token|bearer)\s*[:=]\s*\S{8,}", re.I),
    re.compile(r"\b(?:sk|AIza|ghp|github_pat|xox[baprs])[-_A-Za-z0-9]{16,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.I),
    re.compile(r"\b[A-Z][A-Z0-9_]*(?:TOKEN|KEY|SECRET|PASSWORD)\s*=\s*\S{8,}", re.I),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
)


def contains_sensitive_value(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def safe_memory_text(text: str) -> str:
    # Omit the whole message: partial redaction could leak multiline credentials.
    return "[Credential-like content omitted from memory.]" if contains_sensitive_value(text) else text


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[^\W_]{2,}", text.casefold(), flags=re.UNICODE)
        if token
    }


class JSONLongTermMemory:
    """Atomic JSON-backed long-term memory with replaceable lexical retrieval."""

    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self._lock = Lock()
        self._ensure_file()

    def _ensure_file(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self.file_path.write_text(
                json.dumps({"version": 2, "memories": []}, indent=2),
                encoding="utf-8",
            )

    def _read(self) -> Dict[str, Any]:
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("memories", []), list):
                raise ValueError("Invalid long-term memory document")
            data.setdefault("version", 2)
            data.setdefault("memories", [])
            return cast(Dict[str, Any], data)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Long-term memory at '{self.file_path}' is unreadable; it was not overwritten."
            ) from exc

    def _write(self, data: Dict[str, Any]) -> None:
        temporary = self.file_path.with_suffix(f"{self.file_path.suffix}.tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.file_path)

    @staticmethod
    def _validate_content(content: str) -> str:
        clean = content.strip()
        if not clean:
            raise ValueError("Memory content cannot be empty.")
        if len(clean) > 8_000:
            raise ValueError("Memory content is too long.")
        if contains_sensitive_value(clean):
            raise SensitiveMemoryError(
                "This looks like a password, token, API key, or private key and was not stored."
            )
        return clean

    def create(
        self,
        content: str,
        category: str = "fact",
        source: str = "user",
        confidence: float = 1.0,
        tags: Optional[Sequence[str]] = None,
    ) -> LongTermMemoryEntry:
        clean = self._validate_content(content)
        now = _utc_now()
        entry: LongTermMemoryEntry = {
            "id": str(uuid.uuid4()),
            "content": clean,
            "category": category.strip().lower() or "fact",
            "created_at": now,
            "updated_at": now,
            "source": source.strip() or "user",
            "confidence": max(0.0, min(float(confidence), 1.0)),
            "tags": sorted({tag.strip().casefold() for tag in (tags or []) if tag.strip()}),
        }
        self._validate_content(json.dumps(entry, ensure_ascii=False))
        with self._lock:
            data = self._read()
            cast(List[LongTermMemoryEntry], data["memories"]).append(entry)
            self._write(data)
        return dict(entry)  # type: ignore[return-value]

    def list(
        self,
        category: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 100,
    ) -> List[LongTermMemoryEntry]:
        with self._lock:
            entries = list(
                cast(List[LongTermMemoryEntry], self._read()["memories"])
            )
        if category:
            entries = [item for item in entries if item["category"] == category]
        if query:
            return self.retrieve(query, limit=limit, entries=entries)
        entries.sort(key=lambda item: item["updated_at"], reverse=True)
        return [dict(item) for item in entries[: max(1, min(limit, 500))]]  # type: ignore[misc]

    def get(self, memory_id: str) -> Optional[LongTermMemoryEntry]:
        with self._lock:
            entries = cast(List[LongTermMemoryEntry], self._read()["memories"])
            found = next((item for item in entries if item["id"] == memory_id), None)
            return cast(Optional[LongTermMemoryEntry], dict(found) if found else None)

    def update(
        self,
        memory_id: str,
        content: Optional[str] = None,
        category: Optional[str] = None,
        confidence: Optional[float] = None,
        tags: Optional[Sequence[str]] = None,
    ) -> Optional[LongTermMemoryEntry]:
        with self._lock:
            data = self._read()
            entries = cast(List[LongTermMemoryEntry], data["memories"])
            entry = next((item for item in entries if item["id"] == memory_id), None)
            if entry is None:
                return None
            if content is not None:
                entry["content"] = self._validate_content(content)
            if category is not None:
                entry["category"] = category.strip().lower() or "fact"
            if confidence is not None:
                entry["confidence"] = max(0.0, min(float(confidence), 1.0))
            if tags is not None:
                entry["tags"] = sorted(
                    {tag.strip().casefold() for tag in tags if tag.strip()}
                )
            entry["updated_at"] = _utc_now()
            self._validate_content(json.dumps(entry, ensure_ascii=False))
            self._write(data)
            return cast(LongTermMemoryEntry, dict(entry))

    def delete(self, memory_id: str) -> bool:
        with self._lock:
            data = self._read()
            entries = cast(List[LongTermMemoryEntry], data["memories"])
            remaining = [item for item in entries if item["id"] != memory_id]
            if len(remaining) == len(entries):
                return False
            data["memories"] = remaining
            self._write(data)
            return True

    def retrieve(
        self,
        query: str,
        limit: int = 5,
        categories: Optional[Sequence[str]] = None,
        entries: Optional[Sequence[LongTermMemoryEntry]] = None,
    ) -> List[LongTermMemoryEntry]:
        query_tokens = _tokens(query)
        if not query_tokens:
            return []
        if entries is None:
            with self._lock:
                pool = list(cast(List[LongTermMemoryEntry], self._read()["memories"]))
        else:
            pool = list(entries)
        category_set = {item.casefold() for item in categories or []}
        scored = []
        for entry in pool:
            if category_set and entry["category"].casefold() not in category_set:
                continue
            searchable = " ".join(
                (entry["content"], entry["category"], " ".join(entry["tags"]))
            )
            entry_tokens = _tokens(searchable)
            overlap = query_tokens & entry_tokens
            if not overlap:
                continue
            coverage = len(overlap) / len(query_tokens)
            precision = len(overlap) / max(1, len(entry_tokens))
            phrase_bonus = 0.35 if query.casefold() in searchable.casefold() else 0.0
            score = (coverage * 0.7 + precision * 0.3 + phrase_bonus) * (
                0.5 + entry["confidence"] * 0.5
            )
            scored.append((score, entry["updated_at"], entry))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        bounded = max(1, min(limit, 20))
        return [cast(LongTermMemoryEntry, dict(item[2])) for item in scored[:bounded]]
