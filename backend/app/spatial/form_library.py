"""Read-only adapter onto FORM Character Studio's on-disk project library.

FORM (``products/form``) owns its projects, production versions and artifacts in
``<FORM data dir>/expert.sqlite3`` plus ``projects/<project id>/``. Spatial Lab
does not keep a second character registry: it reads FORM's records through this
adapter, which

* opens the SQLite store with ``mode=ro`` (never writes, never migrates),
* requires the FORM tables it understands and fails closed otherwise,
* numbers versions exactly like FORM's UI (``V01``… in production-link order),
* only exposes GLBs FORM itself verified (``export_readback.verified``) or
  experimental local-shape outputs FORM recorded, and
* returns FORM's recorded SHA-256 so loads can prove version identity.

FORM does not need to be running, and FORM never needs Spatial Lab.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote

CONTRACT = "form-library-read-1"
REQUIRED_TABLES = {"studio_projects", "studio_links", "studio_files", "production_jobs"}


class FormLibraryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def default_data_dirs() -> List[Path]:
    """Where FORM's Electron shell keeps userData on Windows (packaged, then dev)."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return []
    return [Path(appdata) / "FORM Character Studio", Path(appdata) / "form-character-studio"]


class FormLibrary:
    def __init__(self, data_dir: Optional[Path] = None, candidates: Optional[Iterable[Path]] = None) -> None:
        self.configured = data_dir
        self.candidates = list(candidates) if candidates is not None else default_data_dirs()

    # Discovery --------------------------------------------------------------------
    def data_dir(self) -> Path:
        options = [self.configured] if self.configured else self.candidates
        for option in options:
            if option and (Path(option) / "expert.sqlite3").is_file():
                return Path(option).resolve()
        if self.configured:
            raise FormLibraryError("not_found", "The configured FORM data directory has no expert.sqlite3.")
        raise FormLibraryError("not_found", "No FORM library was found. Set AKASHI_FORM_DATA_DIR to FORM's data directory.")

    def status(self) -> Dict[str, Any]:
        try:
            root = self.data_dir()
            with self._connect(root):
                pass
            return {"available": True, "contract": CONTRACT, "reason": None, "configured": bool(self.configured)}
        except FormLibraryError as exc:
            return {"available": False, "contract": CONTRACT, "reason": str(exc), "code": exc.code,
                    "configured": bool(self.configured)}

    def _connect(self, root: Path) -> sqlite3.Connection:
        uri = "file:" + quote(str(root / "expert.sqlite3")) + "?mode=ro"
        try:
            db = sqlite3.connect(uri, uri=True, timeout=2)
            db.row_factory = sqlite3.Row
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        except sqlite3.Error as exc:
            raise FormLibraryError("unreadable", f"FORM library could not be opened read-only ({type(exc).__name__}).") from exc
        missing = REQUIRED_TABLES - tables
        if missing:
            db.close()
            raise FormLibraryError("schema_mismatch", "FORM library schema is not supported (missing " + ", ".join(sorted(missing)) + ").")
        return db

    # Queries ----------------------------------------------------------------------
    def projects(self) -> List[Dict[str, Any]]:
        root = self.data_dir()
        db = self._connect(root)
        try:
            rows = db.execute("SELECT id, body FROM studio_projects ORDER BY rowid DESC").fetchall()
            result = []
            for row in rows:
                project = self._json(row["body"])
                versions = self._versions(db, root, project)
                loadable = [v for v in versions if v["loadable"]]
                result.append({
                    "id": project.get("id", row["id"]),
                    "name": str(project.get("name") or "Untitled")[:120],
                    "created_at": project.get("created_at"),
                    "updated_at": project.get("updated_at"),
                    "best_version": project.get("best_run"),
                    "versions": len(versions),
                    "loadable_versions": len(loadable),
                    "latest_loadable": loadable[-1]["id"] if loadable else None,
                })
            return result
        finally:
            db.close()

    def versions(self, project_id: str) -> List[Dict[str, Any]]:
        root = self.data_dir()
        db = self._connect(root)
        try:
            return [self._public(v) for v in self._versions(db, root, self._project(db, project_id))]
        finally:
            db.close()

    def resolve(self, project_id: str, selector: str) -> Dict[str, Any]:
        """Return one loadable version including its absolute path (server-side only)."""
        root = self.data_dir()
        db = self._connect(root)
        try:
            project = self._project(db, project_id)
            versions = self._versions(db, root, project)
        finally:
            db.close()
        loadable = [v for v in versions if v["loadable"]]
        production = [v for v in loadable if v["kind"] == "production"]
        if selector == "latest":
            if not production:
                raise FormLibraryError("no_version", "This FORM project has no verified production version yet.")
            chosen = production[-1]
        elif selector == "best":
            best = project.get("best_run")
            chosen = next((v for v in production if v["id"] == best), None)
            if not best:
                raise FormLibraryError("no_best", "This FORM project has no pinned best version.")
            if not chosen:
                raise FormLibraryError("not_loadable", "The pinned best version is not a loadable verified export.")
        else:
            chosen = next((v for v in versions if v["id"] == selector), None)
            if not chosen:
                raise FormLibraryError("no_version", "That version does not belong to this FORM project.")
            if not chosen["loadable"]:
                raise FormLibraryError("not_loadable", chosen["reason"] or "That version is not loadable.")
        return {**chosen, "project_id": project.get("id"), "project_name": str(project.get("name") or "Untitled")[:120]}

    # Internals --------------------------------------------------------------------
    @staticmethod
    def _json(raw: str) -> Dict[str, Any]:
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise FormLibraryError("corrupt_record", "A FORM record is not valid JSON.") from exc
        if not isinstance(value, dict):
            raise FormLibraryError("corrupt_record", "A FORM record is not an object.")
        return value

    def _project(self, db: sqlite3.Connection, project_id: str) -> Dict[str, Any]:
        if not isinstance(project_id, str) or not project_id or len(project_id) > 128:
            raise FormLibraryError("no_project", "FORM project id is invalid.")
        row = db.execute("SELECT body FROM studio_projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise FormLibraryError("no_project", "FORM project was not found.")
        return self._json(row["body"])

    @staticmethod
    def _inside(root: Path, project_id: str, raw: Any) -> Optional[Path]:
        if not isinstance(raw, str) or not raw:
            return None
        path = Path(raw)
        project_dir = (root / "projects" / project_id).resolve()
        try:
            if path.is_symlink() or not path.is_file():
                return None
            resolved = path.resolve()
        except OSError:
            return None
        return resolved if resolved.is_relative_to(project_dir) and resolved.suffix.casefold() == ".glb" else None

    def _versions(self, db: sqlite3.Connection, root: Path, project: Dict[str, Any]) -> List[Dict[str, Any]]:
        project_id = project.get("id")
        links = [r[0] for r in db.execute(
            "SELECT target FROM studio_links WHERE project_id=? AND kind='production' ORDER BY created", (project_id,))]
        versions: List[Dict[str, Any]] = []
        for index, run_id in enumerate(links, start=1):
            row = db.execute("SELECT body FROM production_jobs WHERE id=?", (run_id,)).fetchone()
            job = self._json(row["body"]) if row else {}
            application = job.get("application") or {}
            readback = application.get("export_readback") or {}
            path = self._inside(root, project_id, (application.get("paths") or {}).get("glb"))
            reason = None
            if not row:
                reason = "FORM production record is missing."
            elif job.get("status") != "completed_partial":
                reason = f"FORM version is {str(job.get('status', 'unknown')).replace('_', ' ')}."
            elif not readback.get("verified") or not readback.get("sha256"):
                reason = "FORM did not verify this GLB export."
            elif path is None:
                reason = "The exported GLB is missing or outside the FORM project directory."
            versions.append({
                "id": run_id,
                "kind": "production",
                "index": index,
                "label": f"V{index:02d}",
                "status": job.get("status", "missing"),
                "created_at": job.get("created_at"),
                "loadable": reason is None,
                "reason": reason,
                "sha256": readback.get("sha256"),
                "bytes": readback.get("bytes"),
                "skins": readback.get("skins", 0),
                "animations": readback.get("animations", 0),
                "rigged": bool(readback.get("skins")),
                "experimental": False,
                "is_best": project.get("best_run") == run_id,
                "path": path,
            })
        files = {}
        for row in db.execute("SELECT id, body FROM studio_files WHERE project_id=?", (project_id,)):
            files[row["id"]] = self._json(row["body"])
        for job in project.get("shape_jobs", []) or []:
            if not isinstance(job, dict) or job.get("status") != "completed_partial":
                continue
            record = files.get(job.get("output"))
            path = self._inside(root, project_id, (record or {}).get("path"))
            evidence = job.get("evidence") or {}
            versions.append({
                "id": "shape-" + str(job.get("id")),
                "kind": "shape",
                "index": None,
                "label": "LOCAL SHAPE",
                "status": job.get("status"),
                "created_at": job.get("created_at"),
                "loadable": path is not None and bool(evidence.get("output_sha256")),
                "reason": None if path is not None else "Local shape output is missing.",
                "sha256": evidence.get("output_sha256"),
                "bytes": record.get("bytes") if record else None,
                "skins": 0,
                "animations": 0,
                "rigged": False,
                "experimental": True,
                "is_best": False,
                "path": path,
            })
        return versions

    @staticmethod
    def _public(version: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in version.items() if k != "path"}
