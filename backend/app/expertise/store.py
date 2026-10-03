from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class ExpertiseStore:
    """Transactional compact metadata. Source binaries live outside the database."""
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS assets (id TEXT PRIMARY KEY, digest TEXT NOT NULL, parser TEXT NOT NULL,
                    synthetic INTEGER NOT NULL, name TEXT NOT NULL, created_at TEXT NOT NULL, body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS asset_hash ON assets(digest, parser, synthetic);
                CREATE TABLE IF NOT EXISTS knowledge (id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES assets(id),
                    kind TEXT NOT NULL, topic TEXT NOT NULL, validation TEXT NOT NULL, body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS knowledge_asset ON knowledge(asset_id);
                CREATE TABLE IF NOT EXISTS experiences (id TEXT PRIMARY KEY, task_id TEXT NOT NULL UNIQUE,
                    updated_at TEXT NOT NULL, body TEXT NOT NULL);
                PRAGMA user_version=1;
            """)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(str(self.path), timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def cached(self, digest: str, parser: str, synthetic: bool) -> Optional[Dict[str, Any]]:
        with self.connection() as db:
            row = db.execute("SELECT body FROM assets WHERE digest=? AND parser=? AND synthetic=?", (digest, parser, int(synthetic))).fetchone()
        return json.loads(row[0]) if row else None

    def put_asset(self, asset: Dict[str, Any], knowledge: List[Dict[str, Any]]) -> Dict[str, Any]:
        with self.connection() as db:
            # Cache identity includes provenance/version and parser+analyzer revision.
            existing = db.execute("SELECT body FROM assets WHERE id=?", (asset["id"],)).fetchone()
            if existing:
                return json.loads(existing[0])
            db.execute("INSERT INTO assets VALUES(?,?,?,?,?,?,?)", (asset["id"], asset["digest"], asset["pipeline_version"], int(asset["source"]["synthetic"]), asset["name"], asset["created_at"], encode(asset)))
            for item in knowledge:
                db.execute("INSERT INTO knowledge VALUES(?,?,?,?,?,?)", (item["id"], asset["id"], item["kind"], item["topic"], item["validation"], encode(item)))
        return asset

    def asset(self, identifier: str) -> Dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT body FROM assets WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise KeyError("Character asset was not found.")
        return json.loads(row[0])

    def list_assets(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute("SELECT id,name,synthetic,created_at,digest,parser,json_extract(body,'$.analysis.observed.joint_count') AS joint_count,json_extract(body,'$.analysis.observed.mesh_count') AS mesh_count FROM assets ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()
        return [dict(row) for row in rows]

    def knowledge(self, query: str = "", limit: int = 20, asset_id: Optional[str] = None, validated_only: bool = False) -> List[Dict[str, Any]]:
        import re
        tokens = set(re.findall(r"[\w]{3,}", query.casefold()))
        with self.connection() as db:
            rows = db.execute("SELECT body FROM knowledge WHERE (? IS NULL OR asset_id=?) AND (?=0 OR validation='validated')", (asset_id, asset_id, int(validated_only))).fetchall()
        items = [json.loads(row[0]) for row in rows]
        if tokens:
            scored = [(len(tokens & set(re.findall(r"[\w]{3,}", (item["topic"] + " " + item["statement"]).casefold()))), item) for item in items]
            items = [item for score, item in sorted(scored, key=lambda row: row[0], reverse=True) if score]
        return items[:max(1, min(limit, 200))]

    def validate_knowledge(self, identifier: str, evidence: Dict[str, Any]) -> Dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT body FROM knowledge WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise KeyError("Knowledge was not found.")
            item = json.loads(row[0])
            item.setdefault("validation_history", []).append({"at": now(), **evidence})
            item["validation"] = "validated"
            item["epistemic_status"] = "validated_principle" if item["kind"] in {"hypothesis", "inferred_principle"} else item["kind"]
            item["validation_scope"] = "synthetic_only" if item["provenance"]["synthetic"] else "source_specific"
            db.execute("UPDATE knowledge SET validation=?,body=? WHERE id=?", (item["validation"], encode(item), identifier))
        return item

    def save_experience(self, value: Dict[str, Any], connection=None) -> None:
        if connection is None:
            with self.connection() as db:
                self.save_experience(value, db)
            return
        connection.execute("INSERT INTO experiences VALUES(?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET updated_at=excluded.updated_at,body=excluded.body", (value["id"], value["task_id"], now(), encode(value)))

    def experiences(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute("SELECT body FROM experiences ORDER BY updated_at DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
        return [json.loads(row[0]) for row in rows]
