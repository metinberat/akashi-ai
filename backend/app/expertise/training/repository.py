"""SQLite checkpoints, fenced workers and immutable candidate/reference documents."""
import json
import time
import uuid

from app.expertise.store import encode, now
from app.expertise.workshop.repository import digest
from .contracts import GENERATOR_VERSION, TRAINER_VERSION, RECIPE_VERSION
from .evaluation import EVALUATOR_VERSION


class TrainingRepository:
    def __init__(self, store):
        self.store = store
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS training_runs(id TEXT PRIMARY KEY,updated_at TEXT NOT NULL,body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS training_exercises(id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES training_runs(id),body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS training_exercises_run ON training_exercises(run_id);
                CREATE TABLE IF NOT EXISTS training_attempts(id TEXT PRIMARY KEY,exercise_id TEXT NOT NULL REFERENCES training_exercises(id),method_id TEXT NOT NULL,body TEXT NOT NULL,UNIQUE(exercise_id,method_id));
                CREATE INDEX IF NOT EXISTS training_attempts_exercise ON training_attempts(exercise_id);
                CREATE TABLE IF NOT EXISTS training_champions(context TEXT PRIMARY KEY,body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS training_method_history(id TEXT PRIMARY KEY,context TEXT NOT NULL,body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS training_compute_owner(slot INTEGER PRIMARY KEY CHECK(slot=1),run_id TEXT NOT NULL,token TEXT NOT NULL,expires REAL NOT NULL);
            """)

    @staticmethod
    def _document(db, value):
        key = digest(value)
        db.execute("INSERT OR IGNORE INTO character_documents VALUES(?,?)", (key, encode(value)))
        return key

    def document(self, key):
        with self.store.connection() as db:
            row = db.execute("SELECT body FROM character_documents WHERE digest=?", (key,)).fetchone()
        if not row:
            raise KeyError("Training artifact was not found.")
        return json.loads(row[0])

    def create(self, request, recipes):
        value = {"id": "training-"+uuid.uuid4().hex, "request": request.model_dump(), "recipes": recipes,
                 "status": "queued", "created_at": now(), "updated_at": now(), "completed_exercises": 0,
                 "level": request.start_level, "active_exercise": None, "lease_token": None, "lease_until": 0,
                 "pause_requested": False, "cancel_requested": False, "synthetic": True,
                 "versions": {"generator": GENERATOR_VERSION, "trainer": TRAINER_VERSION, "recipe": RECIPE_VERSION, "evaluator": EVALUATOR_VERSION},
                 "scope": "procedural curriculum; no professional asset mastery or model fine-tuning implied"}
        with self.store.connection() as db:
            db.execute("INSERT INTO training_runs VALUES(?,?,?)", (value["id"], now(), encode(value)))
        return value

    def get(self, identifier):
        with self.store.connection() as db:
            row = db.execute("SELECT body FROM training_runs WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise KeyError("Training run was not found.")
        value = json.loads(row[0])
        if value["status"] == "running" and value["lease_until"] < time.time():
            value["status"] = "paused_recovery"
            value["recovery_reason"] = "Worker lease expired; explicit resume replays only uncommitted pure numeric work."
        return value

    def list(self, limit=50):
        with self.store.connection() as db:
            keys = [row[0] for row in db.execute("SELECT id FROM training_runs ORDER BY updated_at DESC LIMIT ?", (min(100, max(1, limit)),))]
        return [self.get(key) for key in keys]

    def claim(self, identifier):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM training_runs WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise KeyError("Training run was not found.")
            value = json.loads(row[0])
            if value["status"] in {"completed", "cancelled", "failed"}:
                return value, None
            if value.get("lease_token") and value["lease_until"] > time.time():
                raise ValueError("A training worker already owns this run.")
            owner = db.execute("SELECT expires FROM training_compute_owner WHERE slot=1").fetchone()
            if owner and owner[0] > time.time():
                raise ValueError("Local numeric training compute is already leased by another run.")
            token = uuid.uuid4().hex
            value.update(lease_token=token, lease_until=time.time()+180, status="running", pause_requested=False, updated_at=now())
            db.execute("UPDATE training_runs SET updated_at=?,body=? WHERE id=?", (now(), encode(value), identifier))
            db.execute("INSERT INTO training_compute_owner VALUES(1,?,?,?) ON CONFLICT(slot) DO UPDATE SET run_id=excluded.run_id,token=excluded.token,expires=excluded.expires", (identifier, token, value["lease_until"]))
        return value, token

    def _owned(self, db, identifier, token):
        row = db.execute("SELECT body FROM training_runs WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise KeyError("Training run was not found.")
        value = json.loads(row[0])
        if value.get("lease_token") != token or value["lease_until"] < time.time():
            raise ValueError("Training worker lease lost; stale result cannot modify checkpoints.")
        owner = db.execute("SELECT run_id,token,expires FROM training_compute_owner WHERE slot=1").fetchone()
        if not owner or owner[0] != identifier or owner[1] != token or owner[2] < time.time():
            raise ValueError("Training compute ownership lost.")
        return value

    @staticmethod
    def _renew(db, identifier, token, value):
        if value["status"] == "running":
            db.execute("UPDATE training_compute_owner SET expires=? WHERE slot=1 AND run_id=? AND token=?", (value["lease_until"], identifier, token))
        else:
            db.execute("DELETE FROM training_compute_owner WHERE slot=1 AND run_id=? AND token=?", (identifier, token))

    def save(self, identifier, token, changes):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            value = self._owned(db, identifier, token)
            value.update(changes, updated_at=now(), lease_until=time.time()+180)
            if value["status"] != "running":
                value.update(lease_token=None, lease_until=0)
            db.execute("UPDATE training_runs SET updated_at=?,body=? WHERE id=?", (now(), encode(value), identifier))
            self._renew(db, identifier, token, value)
        return value

    def request(self, identifier, command):
        if command not in {"pause", "cancel"}:
            raise ValueError("Unknown training control.")
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM training_runs WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise KeyError("Training run was not found.")
            value = json.loads(row[0])
            if value["status"] in {"completed", "cancelled", "failed"}:
                return value
            value[command+"_requested"] = True
            if not value.get("lease_token") or value["lease_until"] < time.time():
                value.update(status="paused" if command == "pause" else "cancelled", lease_token=None, lease_until=0)
            db.execute("UPDATE training_runs SET updated_at=?,body=? WHERE id=?", (now(), encode(value), identifier))
        return value

    def dispatch_failure(self, identifier, category):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM training_runs WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise KeyError("Training run was not found.")
            value = json.loads(row[0])
            # A failed dispatcher has no authority to change another worker's active state.
            if value["status"] not in {"completed", "cancelled", "failed"} and not (value.get("lease_token") and value["lease_until"] > time.time()):
                value.update(status="paused_recovery", recovery_reason="Training dispatch did not acquire compute: "+category,
                             lease_token=None, lease_until=0)
                db.execute("UPDATE training_runs SET updated_at=?,body=? WHERE id=?", (now(), encode(value), identifier))
        return value

    def begin_exercise(self, run_id, token, value, initial, reference):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            run = self._owned(db, run_id, token)
            value.update(input_digest=self._document(db, initial), reference_digest=self._document(db, reference),
                         best_digest=digest(initial), cursor=0, attempts=[], status="running", run_id=run_id, created_at=now())
            db.execute("INSERT INTO training_exercises VALUES(?,?,?)", (value["id"], run_id, encode(value)))
            run.update(active_exercise=value["id"], lease_until=time.time()+180)
            db.execute("UPDATE training_runs SET body=? WHERE id=?", (encode(run), run_id))
            self._renew(db, run_id, token, run)
        return value

    def exercise(self, identifier):
        with self.store.connection() as db:
            row = db.execute("SELECT body FROM training_exercises WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise KeyError("Training exercise was not found.")
        return json.loads(row[0])

    def exercises(self, run_id):
        self.get(run_id)
        with self.store.connection() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM training_exercises WHERE run_id=? ORDER BY rowid", (run_id,))]

    def attempt(self, run_id, token, exercise_id, value, candidate):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            run = self._owned(db, run_id, token)
            exercise = json.loads(db.execute("SELECT body FROM training_exercises WHERE id=? AND run_id=?", (exercise_id, run_id)).fetchone()[0])
            value["artifact_digest"] = self._document(db, candidate) if candidate else None
            db.execute("INSERT INTO training_attempts VALUES(?,?,?,?)",
                       (value["id"], exercise_id, value["method"]["id"], encode(value)))
            exercise["attempts"].append(value["id"])
            exercise["cursor"] += 1
            if value["accepted"]:
                exercise.update(best_digest=value["artifact_digest"], best_evaluation=value["evaluation"], best_method=value["method"]["id"])
            db.execute("UPDATE training_exercises SET body=? WHERE id=?", (encode(exercise), exercise_id))
            run["lease_until"] = time.time()+180
            db.execute("UPDATE training_runs SET body=? WHERE id=?", (encode(run), run_id))
            self._renew(db, run_id, token, run)
        return exercise

    def finish_exercise(self, run_id, token, identifier, next_level, experience=None):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            run = self._owned(db, run_id, token)
            exercise = json.loads(db.execute("SELECT body FROM training_exercises WHERE id=? AND run_id=?", (identifier, run_id)).fetchone()[0])
            exercise.update(status="completed", ended_at=now())
            db.execute("UPDATE training_exercises SET body=? WHERE id=?", (encode(exercise), identifier))
            run.update(completed_exercises=run["completed_exercises"]+1, active_exercise=None, level=next_level, lease_until=time.time()+180)
            db.execute("UPDATE training_runs SET body=? WHERE id=?", (encode(run), run_id))
            if experience is not None:
                self.store.save_experience(experience, db)
            self._renew(db, run_id, token, run)
        return run

    def attempts(self, run_id=None, limit=1000):
        with self.store.connection() as db:
            rows = db.execute("SELECT a.body FROM training_attempts a JOIN training_exercises e ON a.exercise_id=e.id " +
                              ("WHERE e.run_id=? " if run_id else "") + "ORDER BY a.rowid DESC LIMIT ?",
                              ((run_id, min(10000, max(1, limit))) if run_id else (min(10000, max(1, limit)),))).fetchall()
        return [json.loads(row[0]) for row in rows]

    def champions(self):
        with self.store.connection() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM training_champions")]

    def promote(self, context, method, evidence):
        value = {"id": "method-version-"+uuid.uuid4().hex, "context": context, "method": method, "evidence": evidence,
                 "scope": "repeated independent synthetic validation; not professional expertise", "created_at": now()}
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT body FROM training_champions WHERE context=?", (context,)).fetchone()
            if previous and json.loads(previous[0])["method"]["id"] == method["id"]:
                return json.loads(previous[0])
            value["previous_version"] = json.loads(previous[0])["id"] if previous else None
            db.execute("INSERT INTO training_method_history VALUES(?,?,?)", (value["id"], context, encode(value)))
            db.execute("INSERT INTO training_champions VALUES(?,?) ON CONFLICT(context) DO UPDATE SET body=excluded.body", (context, encode(value)))
        return value

    def history(self):
        with self.store.connection() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM training_method_history ORDER BY rowid DESC LIMIT 200")]

    def method_version(self, identifier):
        with self.store.connection() as db:
            row = db.execute("SELECT body FROM training_method_history WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise KeyError("Method version was not found.")
        return json.loads(row[0])
