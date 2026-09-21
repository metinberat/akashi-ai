"""Durable storage for intelligence, briefs, and maintenance proposals.

This store is deliberately separate from conversation and long-term user memory.
Nothing written here is executable authority.
"""

import json
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Sequence, Tuple, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


INTELLIGENCE_STATUSES = {
    "new",
    "reviewed",
    "dismissed",
    "watching",
    "approved_for_test",
    "approved_for_maintenance",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("Intelligence source URL must be HTTP or HTTPS.")
    blocked = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref"}
    query = urlencode([(key, item) for key, item in parse_qsl(parsed.query) if key.casefold() not in blocked])
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc.casefold(), parsed.path.rstrip("/"), query, ""))


def title_key(value: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE))[:300]


class JSONIntelligenceStore:
    """Atomic JSON store with deterministic URL/title deduplication."""

    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self._lock = Lock()
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self._write({"version": 1, "items": [], "briefs": [], "maintenance": []})

    def _read(self) -> Dict[str, Any]:
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Invalid intelligence document")
            for key in ("items", "briefs", "maintenance"):
                if not isinstance(data.get(key, []), list):
                    raise ValueError(f"Invalid intelligence field: {key}")
                data.setdefault(key, [])
            data.setdefault("version", 1)
            return cast(Dict[str, Any], data)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Intelligence store at '{self.file_path}' is unreadable; it was not overwritten."
            ) from exc

    def _write(self, data: Dict[str, Any]) -> None:
        temporary = self.file_path.with_suffix(f"{self.file_path.suffix}.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.file_path)

    def merge_discovery(self, candidate: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
        source = dict(candidate["source"])
        source["url"] = canonical_url(str(source["url"]))
        key = title_key(str(candidate["title"]))
        now = utc_now()
        with self._lock:
            data = self._read()
            items = cast(List[Dict[str, Any]], data["items"])
            existing = next(
                (
                    item for item in items
                    if item.get("title_key") == key
                    or any(entry.get("url") == source["url"] for entry in item.get("sources", []))
                ),
                None,
            )
            if existing is not None:
                matching_source = next(
                    (entry for entry in existing.get("sources", []) if entry.get("url") == source["url"]),
                    None,
                )
                if matching_source is None:
                    existing.setdefault("sources", []).append(source)
                else:
                    matching_source.update(source)
                existing["updated_at"] = now
                existing["duplicate_count"] = max(0, len(existing.get("sources", [])) - 1)
                for field in (
                    "publication_date", "summary",
                    "why_it_matters", "akashi_relevance", "affected_subsystem", "maturity",
                    "risk", "migration_effort", "expected_benefit", "confidence", "priority",
                ):
                    if candidate.get(field) is not None:
                        existing[field] = candidate[field]
                self._write(data)
                return deepcopy(existing), False
            item = {
                "id": str(uuid.uuid4()),
                "discovered_at": now,
                "updated_at": now,
                "title": str(candidate["title"]).strip()[:500],
                "title_key": key,
                "category": str(candidate["category"]).strip()[:100],
                "sources": [source],
                "publication_date": candidate.get("publication_date"),
                "summary": str(candidate.get("summary") or "").strip()[:4_000],
                "why_it_matters": str(candidate.get("why_it_matters") or "").strip()[:2_000],
                "akashi_relevance": str(candidate.get("akashi_relevance") or "general"),
                "affected_subsystem": str(candidate.get("affected_subsystem") or "core"),
                "maturity": str(candidate.get("maturity") or "unknown"),
                "risk": str(candidate.get("risk") or "review"),
                "migration_effort": str(candidate.get("migration_effort") or "unknown"),
                "expected_benefit": str(candidate.get("expected_benefit") or "unverified"),
                "confidence": str(candidate.get("confidence") or "medium"),
                "priority": str(candidate.get("priority") or "background"),
                "duplicate_of": None,
                "duplicate_count": 0,
                "status": "new",
                "read": False,
            }
            items.append(item)
            self._write(data)
            return deepcopy(item), True

    def list_items(
        self,
        category: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._read()["items"])
        if category:
            items = [item for item in items if item.get("category", "").casefold() == category.casefold()]
        if status:
            items = [item for item in items if item.get("status") == status.casefold()]
        items.sort(key=lambda item: item.get("publication_date") or item.get("discovered_at", ""), reverse=True)
        return deepcopy(items[: max(1, min(limit, 500))])

    def get_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            item = next((value for value in self._read()["items"] if value.get("id") == item_id), None)
        return deepcopy(item) if item else None

    def set_status(self, item_id: str, status: str) -> Dict[str, Any]:
        normalized = status.strip().casefold()
        if normalized not in INTELLIGENCE_STATUSES:
            raise ValueError("Unsupported intelligence status.")
        with self._lock:
            data = self._read()
            item = next((value for value in data["items"] if value.get("id") == item_id), None)
            if item is None:
                raise KeyError("Intelligence item was not found.")
            item["status"] = normalized
            item["read"] = True
            item["updated_at"] = utc_now()
            if normalized in {"approved_for_test", "approved_for_maintenance"}:
                queue = data["maintenance"]
                if not any(entry.get("intelligence_id") == item_id for entry in queue):
                    queue.append({
                        "id": str(uuid.uuid4()),
                        "intelligence_id": item_id,
                        "title": item["title"],
                        "status": "queued",
                        "approval": normalized,
                        "created_at": utc_now(),
                        "notes": "Manual/Codex execution only. No automatic production modification.",
                    })
            self._write(data)
            return deepcopy(item)

    def save_brief(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        output = deepcopy(brief)
        output.setdefault("id", str(uuid.uuid4()))
        output.setdefault("created_at", utc_now())
        with self._lock:
            data = self._read()
            data["briefs"].append(output)
            data["briefs"] = data["briefs"][-90:]
            self._write(data)
        return deepcopy(output)

    def list_briefs(self, limit: int = 30) -> List[Dict[str, Any]]:
        with self._lock:
            briefs = list(self._read()["briefs"])
        briefs.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return deepcopy(briefs[: max(1, min(limit, 90))])

    def list_maintenance(self) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._read()["maintenance"])
        items.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return deepcopy(items)
