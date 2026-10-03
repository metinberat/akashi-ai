from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Dict, List, Optional
from app.memory.long_term import contains_sensitive_value


def _tokens(value: str) -> set[str]:
    return {item for item in re.findall(r"[a-z0-9çğıöşü_-]{3,}", value.casefold())}


class KnowledgeStore:
    """Small local lexical RAG foundation. Retrieved text is always untrusted data."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = Lock()
        self.expert_search: Optional[Callable[[str, int], List[Dict[str, Any]]]] = None
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            self._write({"version": 1, "chunks": []})

    def _read(self) -> Dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or not isinstance(value.get("chunks"), list):
                raise ValueError("invalid knowledge store")
            return value
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("Knowledge store is unreadable; it was not overwritten.") from exc

    def _write(self, value: Dict[str, Any]) -> None:
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def ingest(self, title: str, text: str, source: Optional[str] = None, kind: str = "note", metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        clean = text.strip()
        if not clean or len(clean) > 500_000:
            raise ValueError("Knowledge text must contain 1-500000 characters.")
        if contains_sensitive_value(clean + " " + title + " " + str(source or "")):
            raise ValueError("Credential-like content cannot enter durable knowledge.")
        selected_metadata = {key: value for key, value in (metadata or {}).items() if key in {"category", "authority", "confidence", "version", "asset_id", "synthetic", "validation", "method", "knowledge_id"}}
        chunks = []
        for offset in range(0, len(clean), 3500):
            content = clean[offset: offset + 4000]
            digest = hashlib.sha256((str(source or "") + kind + json.dumps(selected_metadata, sort_keys=True) + content).encode("utf-8")).hexdigest()
            chunks.append({
                "id": digest[:24], "title": title[:300], "source": str(source or "")[:2000],
                "kind": kind[:60], "content": content, "created_at": datetime.now(timezone.utc).isoformat(),
                "untrusted": True,
                "metadata": selected_metadata,
            })
        with self._lock:
            data = self._read()
            existing = {item.get("id") for item in data["chunks"]}
            created = [item for item in chunks if item["id"] not in existing]
            data["chunks"].extend(created)
            data["chunks"] = data["chunks"][-5000:]
            self._write(data)
        return {"created": len(created), "total_chunks": len(chunks)}

    def search(self, query: str, limit: int = 6) -> List[Dict[str, Any]]:
        wanted = _tokens(query)
        with self._lock:
            chunks = list(self._read()["chunks"])
        scored = []
        for item in chunks:
            body = _tokens(str(item.get("title") or "") + " " + str(item.get("content") or ""))
            overlap = len(wanted.intersection(body))
            if overlap:
                coverage = overlap / max(1, len(wanted))
                scored.append((coverage, overlap, item))
        scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
        bound = max(1, min(limit, 20))
        expert = self.expert_search(query, max(1, bound // 2)) if self.expert_search else []
        return deepcopy(expert + [item for _, _, item in scored[:bound - len(expert)]])
