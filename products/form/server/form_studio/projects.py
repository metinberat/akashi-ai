import hashlib
import json
import uuid
from pathlib import Path

from app.expertise.store import encode, now
from app.expertise.production.contracts import Design


class Projects:
    """Independent project aggregate on the domain's transactional SQLite connection."""

    def __init__(self, store, root):
        self.store, self.root = store, Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS studio_projects(id TEXT PRIMARY KEY,body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS studio_links(project_id TEXT NOT NULL,kind TEXT NOT NULL,
                    target TEXT NOT NULL,created TEXT NOT NULL,PRIMARY KEY(project_id,kind,target));
                CREATE TABLE IF NOT EXISTS studio_files(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,
                    body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS studio_messages(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,
                    body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS studio_quarantine(sha256 TEXT PRIMARY KEY,
                    backend TEXT NOT NULL,created TEXT NOT NULL);
            """)

    def create(self, name, brief):
        value = {
            "id": uuid.uuid4().hex,
            "name": name,
            "brief": brief,
            "created_at": now(),
            "updated_at": now(),
            "design": Design(appearance="atelier").model_dump(),
            "best_run": None,
        }
        with self.store.connection() as db:
            db.execute(
                "INSERT INTO studio_projects VALUES(?,?)", (value["id"], encode(value))
            )
        self.directory(value["id"])
        return value

    def quarantine(self, digest, backend):
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("Invalid artifact fingerprint.")
        with self.store.connection() as db:
            db.execute(
                "INSERT OR IGNORE INTO studio_quarantine VALUES(?,?,?)",
                (digest, backend, now()),
            )

    def quarantined(self, digest):
        with self.store.connection() as db:
            return (
                db.execute(
                    "SELECT 1 FROM studio_quarantine WHERE sha256=?", (digest,)
                ).fetchone()
                is not None
            )

    def get(self, key):
        with self.store.connection() as db:
            row = db.execute(
                "SELECT body FROM studio_projects WHERE id=?", (key,)
            ).fetchone()
        if not row:
            raise KeyError("Project not found.")
        return json.loads(row[0])

    def list(self):
        with self.store.connection() as db:
            return [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT body FROM studio_projects ORDER BY rowid DESC"
                )
            ]

    def update(self, key, changes):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT body FROM studio_projects WHERE id=?", (key,)
            ).fetchone()
            if not row:
                raise KeyError("Project not found.")
            value = json.loads(row[0])
            value.update(changes, updated_at=now())
            db.execute(
                "UPDATE studio_projects SET body=? WHERE id=?", (encode(value), key)
            )
        return value

    def directory(self, key):
        self.get(key)
        path = self.root / key
        path.mkdir(exist_ok=True)
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("Project directory escaped storage.")
        return path

    def link(self, key, kind, target):
        self.get(key)
        with self.store.connection() as db:
            db.execute(
                "INSERT OR IGNORE INTO studio_links VALUES(?,?,?,?)",
                (key, kind, target, now()),
            )

    def links(self, key, kind):
        self.get(key)
        with self.store.connection() as db:
            return [
                r[0]
                for r in db.execute(
                    "SELECT target FROM studio_links WHERE project_id=? AND kind=? ORDER BY created",
                    (key, kind),
                )
            ]

    def require_link(self, key, kind, target):
        if target not in self.links(key, kind):
            raise KeyError("Result does not belong to this project.")

    def message(self, key, role, text, evidence=None):
        self.get(key)
        value = {
            "id": uuid.uuid4().hex,
            "role": role,
            "text": text[:8000],
            "at": now(),
            "evidence": evidence,
        }
        with self.store.connection() as db:
            db.execute(
                "INSERT INTO studio_messages VALUES(?,?,?)",
                (value["id"], key, encode(value)),
            )
        return value

    def messages(self, key):
        self.get(key)
        with self.store.connection() as db:
            rows = db.execute(
                "SELECT body FROM studio_messages WHERE project_id=? ORDER BY rowid DESC LIMIT 100",
                (key,),
            ).fetchall()
        return [json.loads(r[0]) for r in reversed(rows)]

    def file(self, key, path, kind, label, run_id=None):
        path = Path(path).resolve()
        if (
            not path.is_relative_to(self.directory(key).resolve())
            or not path.is_file()
            or path.is_symlink()
        ):
            raise ValueError("Artifact is outside its project.")
        identifier = hashlib.sha256((key + str(path)).encode()).hexdigest()[:32]
        value = {
            "id": identifier,
            "kind": kind,
            "label": label[:180],
            "path": str(path),
            "bytes": path.stat().st_size,
            "run_id": run_id,
            "created_at": now(),
        }
        with self.store.connection() as db:
            db.execute(
                "INSERT OR IGNORE INTO studio_files VALUES(?,?,?)",
                (identifier, key, encode(value)),
            )
        return value

    def files(self, key):
        self.get(key)
        with self.store.connection() as db:
            return [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT body FROM studio_files WHERE project_id=? ORDER BY rowid",
                    (key,),
                )
            ]

    def resolve_file(self, key, identifier):
        value = next((f for f in self.files(key) if f["id"] == identifier), None)
        if not value:
            raise KeyError("Artifact not found.")
        path = Path(value["path"]).resolve()
        if not path.is_relative_to(self.directory(key).resolve()) or not path.is_file():
            raise ValueError("Artifact no longer available inside project storage.")
        return path, value
