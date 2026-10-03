from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any, Dict

from app.expertise.store import ExpertiseStore, encode, now


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()).hexdigest()


class WorkshopRepository:
    """Immutable content-addressed documents, append-only attempts, atomic best pointer.

    The SQLite adapter can be replaced without changing the evaluator/controller.
    Leases prevent duplicate workers; expired work requires explicit resume.
    """
    def __init__(self, store: ExpertiseStore):
        self.store = store
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS character_workshops(id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS character_documents(digest TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS character_versions(id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES character_workshops(id),
                    digest TEXT NOT NULL REFERENCES character_documents(digest), created_at TEXT NOT NULL, body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS workshop_versions ON character_versions(job_id,created_at);
                CREATE TABLE IF NOT EXISTS character_application_evidence(id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES character_versions(id), body TEXT NOT NULL);
            """)

    def create(self, job, document, evaluation):
        version = {"id": "version-" + uuid.uuid4().hex, "job_id": job["id"], "created_at": now(), "parent": None,
                   "recipe": None, "decision": {"accepted": True, "reasons": ["Immutable source baseline."]}, "evaluation": evaluation,
                   "digest": digest(document), "synthetic": job["synthetic"], "source_digest": job["source_digest"]}
        job.update(best_version=version["id"], baseline_version=version["id"], attempts=0, status="queued", cancel_requested=False,
                   lease_token=None, lease_until=0, created_at=now(), updated_at=now())
        with self.store.connection() as db:
            db.execute("INSERT INTO character_workshops VALUES(?,?,?)", (job["id"], now(), encode(job)))
            db.execute("INSERT OR IGNORE INTO character_documents VALUES(?,?)", (version["digest"], encode(document)))
            db.execute("INSERT INTO character_versions VALUES(?,?,?,?,?)", (version["id"], job["id"], version["digest"], now(), encode(version)))
        return job

    def get(self, identifier):
        with self.store.connection() as db:
            row = db.execute("SELECT body FROM character_workshops WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise KeyError("Character improvement was not found.")
        job = json.loads(row[0])
        if job["status"] == "running" and job.get("lease_until", 0) < time.time():
            job["status"] = "paused_recovery"
            job["recovery_reason"] = "Worker lease expired. Best checkpoint is intact; resume is explicit."
        return job

    def list(self, limit=50):
        with self.store.connection() as db:
            rows = db.execute("SELECT id FROM character_workshops ORDER BY updated_at DESC LIMIT ?", (min(100, max(1, limit)),)).fetchall()
        return [self.get(row[0]) for row in rows]

    def version(self, identifier, include_document=True):
        with self.store.connection() as db:
            row = db.execute("SELECT v.body,d.body FROM character_versions v JOIN character_documents d ON v.digest=d.digest WHERE v.id=?", (identifier,)).fetchone()
        if not row:
            raise KeyError("Character version was not found.")
        version = json.loads(row[0])
        if include_document:
            version["document"] = json.loads(row[1])
        with self.store.connection() as db:
            version["application_evidence"] = [json.loads(r[0]) for r in db.execute("SELECT body FROM character_application_evidence WHERE version_id=?", (identifier,))]
        return version

    def versions(self, identifier):
        self.get(identifier)
        with self.store.connection() as db:
            rows = db.execute("SELECT body FROM character_versions WHERE job_id=? ORDER BY created_at,id", (identifier,)).fetchall()
            evidence = db.execute("SELECT e.version_id,e.body FROM character_application_evidence e JOIN character_versions v ON e.version_id=v.id WHERE v.job_id=?", (identifier,)).fetchall()
        items = [json.loads(row[0]) for row in rows]
        by_version = {}
        for row in evidence:
            value = json.loads(row[1])
            by_version.setdefault(row[0], []).append({key: value.get(key) for key in ("id", "accepted", "reasons", "scope", "at", "authority", "artifacts")})
        for item in items:
            item["application_evidence"] = by_version.get(item["id"], [])
        return items

    def claim(self, identifier, verification=False):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM character_workshops WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise KeyError("Character improvement was not found.")
            job = json.loads(row[0])
            if job["status"] in {"completed", "cancelled"} and not verification:
                return job, None
            if job.get("lease_until", 0) > time.time() and job.get("lease_token"):
                raise ValueError("Improvement is already running.")
            token = uuid.uuid4().hex
            job.update(status="running", lease_token=token, lease_until=time.time()+120, updated_at=now())
            db.execute("UPDATE character_workshops SET updated_at=?,body=? WHERE id=?", (now(), encode(job), identifier))
        return job, token

    def attach_application_evidence(self, identifier, version_id, evidence, token=None):
        version = self.version(version_id, False)
        if version["job_id"] != identifier:
            raise ValueError("Application evidence belongs to another improvement.")
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM character_workshops WHERE id=?", (identifier,)).fetchone()
            job = json.loads(row[0])
            if job.get("lease_until", 0) > time.time() and job.get("lease_token") != token:
                raise ValueError("Another worker owns this improvement.")
            if token and (job.get("lease_token") != token or job.get("lease_until", 0) < time.time()):
                raise ValueError("Verification lease lost.")
            record = {**evidence, "id": "application-evidence-"+uuid.uuid4().hex, "at": now(), "version_id": version_id}
            db.execute("INSERT INTO character_application_evidence VALUES(?,?,?)", (record["id"], version_id, encode(record)))
            job["application_validation"] = "passed" if evidence["accepted"] else "failed_or_unverified"
            quality_regression = not evidence["accepted"] and str(evidence.get("scope", "")).startswith("actual_application")
            if quality_regression:
                # Reject the affected branch, including later descendants. Raw source is
                # the conservative fallback when real application evidence disagrees.
                cursor = job["best_version"]
                while cursor:
                    candidate = db.execute("SELECT body FROM character_versions WHERE id=?", (cursor,)).fetchone()
                    value = json.loads(candidate[0])
                    if cursor == version_id:
                        job["best_version"] = job["baseline_version"]
                        job.setdefault("rollback_history", []).append({"from": cursor, "to": job["baseline_version"], "at": now(), "reason": "Application verification rejected branch."})
                        break
                    cursor = value["parent"]
                # Actual application feedback creates alternative bounded strategies.
                # It cannot increase the user's attempt budget or enable new action types.
                if job.get("application_replans", 0) < 3 and job["attempts"] < job["max_attempts"]:
                    alternatives = [{"operation": "smooth_weights", "strength": strength, "iterations": 2, "max_influences": 4}
                                    for strength in (.05, .15, .35)]
                    job["next_proposal"] = len(job["proposals"])
                    job["proposals"].extend(alternatives)
                    job["application_replans"] = job.get("application_replans", 0)+1
                    job["replan_evidence"] = record["id"]
            db.execute("UPDATE character_workshops SET updated_at=?,body=? WHERE id=?", (now(), encode(job), identifier))
        return record

    def rejected_in_application(self, source_digest, candidate_digest):
        with self.store.connection() as db:
            row = db.execute("""SELECT 1 FROM character_application_evidence e JOIN character_versions v ON e.version_id=v.id
                JOIN character_workshops j ON v.job_id=j.id WHERE v.digest=? AND json_extract(j.body,'$.source_digest')=?
                AND json_extract(e.body,'$.accepted')=0 AND json_extract(e.body,'$.scope') LIKE 'actual_application%' LIMIT 1""", (candidate_digest, source_digest)).fetchone()
        return bool(row)

    def checkpoint(self, identifier, token, changes: Dict[str, Any], version=None, document=None):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM character_workshops WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise KeyError("Character improvement was not found.")
            job = json.loads(row[0])
            if job.get("lease_token") != token or job.get("lease_until", 0) < time.time():
                raise ValueError("Worker lost ownership; checkpoint rejected.")
            if version is not None:
                if job.get("cancel_requested"):
                    version["decision"] = {**version["decision"], "accepted": False, "reasons": ["Candidate superseded by cancellation."]}
                db.execute("INSERT OR IGNORE INTO character_documents VALUES(?,?)", (version["digest"], encode(document)))
                db.execute("INSERT INTO character_versions VALUES(?,?,?,?,?)", (version["id"], identifier, version["digest"], now(), encode(version)))
                if version["decision"]["accepted"] and not job.get("cancel_requested"):
                    job["best_version"] = version["id"]
                job["attempts"] += 1
            job.update(changes, updated_at=now())
            if job["status"] == "running":
                job["lease_until"] = time.time()+120
            else:
                job.update(lease_token=None, lease_until=0)
            db.execute("UPDATE character_workshops SET updated_at=?,body=? WHERE id=?", (now(), encode(job), identifier))
        return job

    def cancel(self, identifier):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM character_workshops WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise KeyError("Character improvement was not found.")
            job = json.loads(row[0])
            job["cancel_requested"] = True
            if job["status"] != "running" or job.get("lease_until", 0) < time.time():
                job.update(status="cancelled", lease_token=None, lease_until=0)
            db.execute("UPDATE character_workshops SET updated_at=?,body=? WHERE id=?", (now(), encode(job), identifier))
        return self.get(identifier)

    def rollback(self, identifier, version_id):
        version = self.version(version_id, False)
        if (version["job_id"] != identifier or not version["decision"]["accepted"]
            or any(not e["accepted"] and str(e.get("scope", "")).startswith("actual_application") for e in version["application_evidence"])):
            raise ValueError("Rollback target must be an accepted version of this improvement.")
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM character_workshops WHERE id=?", (identifier,)).fetchone()
            job = json.loads(row[0])
            if job.get("lease_until", 0) > time.time() and job.get("lease_token"):
                raise ValueError("Cancel/wait for the active worker before rollback.")
            job.setdefault("rollback_history", []).append({"from": job["best_version"], "to": version_id, "at": now()})
            job.update(best_version=version_id, status="paused", lease_token=None, lease_until=0)
            db.execute("UPDATE character_workshops SET updated_at=?,body=? WHERE id=?", (now(), encode(job), identifier))
        return job

    def evidence(self, include_synthetic=False):
        with self.store.connection() as db:
            rows = db.execute("SELECT v.body,j.body FROM character_versions v JOIN character_workshops j ON v.job_id=j.id").fetchall()
            rejected = {row[0] for row in db.execute("SELECT version_id FROM character_application_evidence WHERE json_extract(body,'$.accepted')=0 AND json_extract(body,'$.scope') LIKE 'actual_application%'")}
        groups = {}
        for row in rows:
            version, job = json.loads(row[0]), json.loads(row[1])
            if not version.get("recipe") or job["synthetic"] and not include_synthetic:
                continue
            key = (version["recipe"]["operation"], job["synthetic"])
            group = groups.setdefault(key, {"operation": key[0], "synthetic": key[1], "positive_sources": set(), "negative_sources": set(), "attempts": 0, "version_references": []})
            group["attempts"] += 1
            bucket = "positive_sources" if version["decision"]["accepted"] and version["id"] not in rejected else "negative_sources"
            group[bucket].add(job.get("evidence_group", job["source_digest"]))
            if len(group["version_references"]) < 100:
                group["version_references"].append(version["id"])
        result = []
        for value in groups.values():
            positive, negative = value.pop("positive_sources"), value.pop("negative_sources")
            result.append({**value, "independent_positive_sources": len(positive), "independent_negative_sources": len(negative),
                "confidence": len(positive)/(len(positive)+len(negative)+3),
                "status": "repeated_scoped_evidence" if len(positive) >= 3 else "source_specific_evidence",
                "scope": "synthetic_numeric_tests" if value["synthetic"] else "asset_specific_numeric_tests",
                "universal_principle": False})
        return result
