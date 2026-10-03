import json
import time
import uuid
from app.expertise.store import now, encode
from app.expertise.workshop.repository import digest
from .contracts import VERSION


class ProductionRepository:
    def __init__(self, store):
        self.store = store
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS production_jobs(id TEXT PRIMARY KEY,body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS production_trials(id TEXT PRIMARY KEY,job_id TEXT NOT NULL,body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS production_owner(slot INTEGER PRIMARY KEY CHECK(slot=1),token TEXT NOT NULL,expires REAL NOT NULL);
            """)

    def create(self, request, reference, expertise):
        value = {
            "id": "production-" + uuid.uuid4().hex,
            "version": VERSION,
            "request": request.model_dump(),
            "reference": reference,
            "expertise": expertise,
            "status": "planned",
            "created_at": now(),
            "updated_at": now(),
            "cursor": 0,
            "best": None,
            "pause_requested": False,
            "cancel_requested": False,
            "lease": None,
            "expires": 0,
            "events": [],
            "mode": "supplied_asset"
            if request.source_asset_id
            else "procedural_character",
        }
        with self.store.connection() as db:
            db.execute(
                "INSERT INTO production_jobs VALUES(?,?)", (value["id"], encode(value))
            )
        return value

    def get(self, key):
        with self.store.connection() as db:
            row = db.execute(
                "SELECT body FROM production_jobs WHERE id=?", (key,)
            ).fetchone()
        if not row:
            raise KeyError("Production job was not found.")
        value = json.loads(row[0])
        if value.get("lease") and value["expires"] < time.time():
            value.update(
                status="paused_recovery",
                recovery_reason="Worker expired; application effects must be reconciled before retry.",
            )
        return value

    def list(self):
        with self.store.connection() as db:
            keys = [
                r[0]
                for r in db.execute(
                    "SELECT id FROM production_jobs ORDER BY rowid DESC LIMIT 100"
                )
            ]
        return [self.get(k) for k in keys]

    def claim(self, key):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT body FROM production_jobs WHERE id=?", (key,)
            ).fetchone()
            if not row:
                raise KeyError("Production job was not found.")
            value = json.loads(row[0])
            if value["status"] in {"completed_partial", "cancelled"}:
                return value, None
            owner = db.execute(
                "SELECT expires FROM production_owner WHERE slot=1"
            ).fetchone()
            if owner and owner[0] > time.time():
                raise ValueError("Production compute is already owned.")
            token = uuid.uuid4().hex
            value.update(
                lease=token,
                expires=time.time() + 900,
                status="building",
                pause_requested=False,
            )
            db.execute(
                "INSERT INTO production_owner VALUES(1,?,?) ON CONFLICT(slot) DO UPDATE SET token=excluded.token,expires=excluded.expires",
                (token, value["expires"]),
            )
            db.execute(
                "UPDATE production_jobs SET body=? WHERE id=?", (encode(value), key)
            )
        return value, token

    def save(
        self,
        key,
        token,
        changes,
        release=False,
        trial=None,
        document=None,
        experience=None,
    ):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT body FROM production_jobs WHERE id=?", (key,)
            ).fetchone()
            if not row:
                raise KeyError("Production job was not found.")
            value = json.loads(row[0])
            owner = db.execute(
                "SELECT token,expires FROM production_owner WHERE slot=1"
            ).fetchone()
            if (
                value["lease"] != token
                or not owner
                or owner[0] != token
                or owner[1] < time.time()
            ):
                raise ValueError("Stale production worker.")
            at = now()
            events = value.get("events", [])
            if changes.get("status") and changes["status"] != value["status"]:
                events.append({"kind": "state", "status": changes["status"], "at": at})
            if trial:
                events.append({"kind": "candidate_evaluated", "trial_id": trial["id"], "accepted": trial["accepted"],
                               "loss": trial["evaluation"]["loss"], "defects": trial["evaluation"]["defects"], "at": at})
            old_steps = (value.get("active_application") or {}).get("done", [])
            new_steps = (changes.get("active_application") or {}).get("done", [])
            for step in new_steps:
                if step not in old_steps:
                    events.append({"kind": "application_receipt", "step": step, "at": at})
            value.update(changes, updated_at=at, expires=time.time() + 900, events=events[-500:])
            if trial:
                if document:
                    trial["document_digest"] = digest(document)
                    db.execute(
                        "INSERT OR IGNORE INTO character_documents VALUES(?,?)",
                        (trial["document_digest"], encode(document)),
                    )
                db.execute(
                    "INSERT INTO production_trials VALUES(?,?,?)",
                    (trial["id"], key, encode(trial)),
                )
            if experience:
                self.store.save_experience(experience, db)
            if release:
                value.update(lease=None, expires=0)
                db.execute("DELETE FROM production_owner WHERE token=?", (token,))
            else:
                db.execute(
                    "UPDATE production_owner SET expires=? WHERE token=?",
                    (value["expires"], token),
                )
            db.execute(
                "UPDATE production_jobs SET body=? WHERE id=?", (encode(value), key)
            )
        return value

    def request(self, key, command):
        if command not in {"pause", "cancel"}:
            raise ValueError("Unknown production control.")
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT body FROM production_jobs WHERE id=?", (key,)
            ).fetchone()
            if not row:
                raise KeyError("Production job was not found.")
            value = json.loads(row[0])
            if value["status"] in {"completed_partial", "cancelled"}:
                return value
            value[command + "_requested"] = True
            if not value.get("lease") or value["expires"] < time.time():
                value.update(
                    status="paused" if command == "pause" else "cancelled",
                    lease=None,
                    expires=0,
                )
            db.execute(
                "UPDATE production_jobs SET body=? WHERE id=?", (encode(value), key)
            )
        return value

    def dispatch_failure(self, key, category):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT body FROM production_jobs WHERE id=?", (key,)
            ).fetchone()
            if not row:
                raise KeyError("Production job was not found.")
            value = json.loads(row[0])
            if value["status"] not in {"completed_partial", "cancelled"} and not (
                value.get("lease") and value["expires"] > time.time()
            ):
                value.update(
                    status="paused_recovery",
                    recovery_reason="Worker dispatch failed: " + category,
                )
                db.execute(
                    "UPDATE production_jobs SET body=? WHERE id=?", (encode(value), key)
                )
        return value

    def trials(self, key):
        self.get(key)
        with self.store.connection() as db:
            return [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT body FROM production_trials WHERE job_id=? ORDER BY rowid",
                    (key,),
                )
            ]

    def document(self, key):
        with self.store.connection() as db:
            row = db.execute(
                "SELECT body FROM character_documents WHERE digest=?", (key,)
            ).fetchone()
        if not row:
            raise KeyError("Production document was not found.")
        return json.loads(row[0])

    def lessons(self):
        with self.store.connection() as db:
            rows = [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT body FROM production_trials ORDER BY rowid DESC LIMIT 1000"
                )
            ]
        groups = {}
        for r in rows:
            if not r.get("evaluation"):
                continue
            spec = r["method"]
            key = encode(spec)
            g = groups.setdefault(
                key,
                {
                    "method": spec,
                    "worlds": {},
                    "scope": "synthetic procedural authoring only",
                },
            )
            g["worlds"].setdefault(r["independent_world"], r["evaluation"])
        result = []
        for g in groups.values():
            worlds = list(g.pop("worlds").values())
            wins = sum(w["passed"] for w in worlds)
            result.append(
                {
                    **g,
                    "independent_worlds": len(worlds),
                    "successes": wins,
                    "confidence": (wins + 1) / (len(worlds) + 2),
                    "mean_loss": sum(w["loss"] for w in worlds) / len(worlds),
                    "professional_validated": False,
                }
            )
        return result
