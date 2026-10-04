"""Spatial asset registry: inspected GLBs addressed by their SHA-256.

Sources:

* ``upload``  — bytes stored once under ``<spatial dir>/assets/uploads/<sha>.glb``.
* ``form``    — FORM artifacts read in place through ``FormLibrary``; never copied
  or modified. Their bytes must hash to the digest FORM recorded at export,
  otherwise the load is refused (version identity check).
* ``fixture`` — the built-in synthetic calibration block.

The registry keeps the full inspection; scene objects embed a compact summary.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.spatial import glb
from app.spatial.fixtures import CALIBRATION_LABEL, calibration_fixture
from app.spatial.form_library import FormLibrary, FormLibraryError
from app.spatial.model import SHA256


class AssetError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _label(name: str, fallback: str) -> str:
    stem = Path(name.replace("\\", "/")).stem if name else ""
    stem = re.sub(r"[^\w .()\-]+", "", stem, flags=re.UNICODE).strip()[:60]
    return stem or fallback


class AssetRegistry:
    def __init__(self, root: Path, form: FormLibrary) -> None:
        self.root = Path(root)
        self.uploads = self.root / "uploads"
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.index_file = self.root / "index.json"
        self.form = form
        self._lock = threading.RLock()
        self._hash_cache: Dict[str, tuple] = {}
        self._index: Dict[str, Dict[str, Any]] = self._load()

    # Persistence ------------------------------------------------------------------
    def _load(self) -> Dict[str, Dict[str, Any]]:
        if not self.index_file.exists():
            return {}
        try:
            value = json.loads(self.index_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Spatial asset index at '{self.index_file}' is unreadable; it was not overwritten.") from exc
        if not isinstance(value, dict) or value.get("schema") != "akashi.spatial.assets/1":
            raise RuntimeError("Spatial asset index has an unsupported schema; it was not overwritten.")
        return value.get("assets", {})

    def _save(self) -> None:
        temporary = self.index_file.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"schema": "akashi.spatial.assets/1", "assets": self._index}, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.index_file)

    # Registration -----------------------------------------------------------------
    def _register(self, data: bytes, source: str, label: str, location: Dict[str, Any], provenance: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        try:
            inspection = glb.inspect(data)
        except glb.GlbInvalid as exc:
            raise AssetError(exc.code, str(exc)) from exc
        sha = inspection["sha256"]
        record = {
            "asset_id": sha,
            "source": source,
            "label": label,
            "location": location,
            "form": provenance,
            "inspection": inspection,
            "registered_at": _now(),
        }
        with self._lock:
            # Content addressing: identical bytes keep their first stored location,
            # while the caller's summary carries the provenance it asked for.
            if sha not in self._index:
                self._index[sha] = record
                self._save()
            elif self._index[sha]["inspection"].get("inspector") != inspection["inspector"]:
                # Re-inspected by a newer inspector: refresh metadata, keep the stored location.
                self._index[sha]["inspection"] = inspection
                self._save()
        return self.summary(record)

    def register_upload(self, data: bytes, filename: str) -> Dict[str, Any]:
        if len(data) > glb.MAX_GLB_BYTES:
            raise AssetError("too_large", f"GLB exceeds the {glb.MAX_GLB_BYTES // (1024 * 1024)} MiB Spatial Lab budget.")
        if not filename.casefold().endswith(".glb"):
            raise AssetError("unsupported_format", "Spatial Lab V1 loads binary .glb files only.")
        sha = _sha(data)
        path = self.uploads / (sha + ".glb")
        summary = self._register(data, "upload", _label(filename, "Uploaded GLB"), {"kind": "upload", "file": path.name}, None)
        if not path.exists():
            temporary = path.with_suffix(".glb.tmp")
            temporary.write_bytes(data)
            temporary.replace(path)
        return summary

    def register_fixture(self) -> Dict[str, Any]:
        return self._register(calibration_fixture(), "fixture", CALIBRATION_LABEL, {"kind": "fixture", "name": "calibration"}, None)

    def register_form(self, project_id: str, selector: str) -> Dict[str, Any]:
        try:
            version = self.form.resolve(project_id, selector)
        except FormLibraryError as exc:
            raise AssetError("form_" + exc.code, str(exc)) from exc
        path: Path = version["path"]
        data = self._read_bounded(path)
        actual = _sha(data)
        if version.get("sha256") != actual:
            raise AssetError("identity_mismatch",
                             f"FORM {version['label']} on disk does not match the digest FORM recorded at export. Refusing to load a different file.")
        provenance = {
            "project_id": version["project_id"],
            "project_name": version["project_name"],
            "version_id": version["id"],
            "version_label": version["label"],
            "version_index": version["index"],
            "version_kind": version["kind"],
            "created_at": version["created_at"],
            "is_best_at_import": version["is_best"],
            "rigged": version["rigged"],
            "experimental": version["experimental"],
            "recorded_sha256": version["sha256"],
            "identity_verified": True,
        }
        label = f"{version['project_name']} {version['label']}"[:80]
        return self._register(data, "form", label, {"kind": "form", "project_id": version["project_id"], "version_id": version["id"]}, provenance)

    def latest_form(self) -> Dict[str, Any]:
        """Most recently created verified production version across FORM projects."""
        try:
            projects = self.form.projects()
        except FormLibraryError as exc:
            raise AssetError("form_" + exc.code, str(exc)) from exc
        best = None
        for project in projects:
            if not project["latest_loadable"]:
                continue
            for version in self.form.versions(project["id"]):
                if version["loadable"] and version["kind"] == "production":
                    key = (version.get("created_at") or "", version["id"])
                    if best is None or key > best[0]:
                        best = (key, project["id"], version["id"])
        if best is None:
            raise AssetError("form_no_version", "No FORM project has a verified production version yet.")
        return self.register_form(best[1], best[2])

    # Access -----------------------------------------------------------------------
    @staticmethod
    def _read_bounded(path: Path) -> bytes:
        try:
            size = path.stat().st_size
            if size > glb.MAX_GLB_BYTES:
                raise AssetError("too_large", f"GLB exceeds the {glb.MAX_GLB_BYTES // (1024 * 1024)} MiB Spatial Lab budget.")
            return path.read_bytes()
        except OSError as exc:
            raise AssetError("unavailable", "Asset file is no longer readable.") from exc

    def record(self, asset_id: str) -> Dict[str, Any]:
        if not isinstance(asset_id, str) or not SHA256.match(asset_id):
            raise AssetError("not_found", "Asset id is invalid.")
        with self._lock:
            record = self._index.get(asset_id)
        if record is None:
            raise AssetError("not_found", "Asset is not registered.")
        return copy.deepcopy(record)

    def content(self, asset_id: str) -> bytes:
        record = self.record(asset_id)
        location = record["location"]
        if location["kind"] == "upload":
            data = self._read_bounded(self.uploads / (asset_id + ".glb"))
        elif location["kind"] == "fixture":
            data = calibration_fixture()
        else:
            try:
                version = self.form.resolve(location["project_id"], location["version_id"])
            except FormLibraryError as exc:
                raise AssetError("form_" + exc.code, str(exc)) from exc
            data = self._read_bounded(version["path"])
        if _sha(data) != asset_id:
            raise AssetError("identity_mismatch", "Asset bytes changed since registration; refusing to serve a different file.")
        return data

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            records = [copy.deepcopy(r) for r in self._index.values()]
        return [self.summary(r) for r in sorted(records, key=lambda r: r["registered_at"], reverse=True)]

    @staticmethod
    def summary(record: Dict[str, Any]) -> Dict[str, Any]:
        inspection = record["inspection"]
        return {
            "asset_id": record["asset_id"],
            "sha256": record["asset_id"],
            "format": "glb",
            "source": record["source"],
            "label": record["label"],
            "bytes": inspection["bytes"],
            "clips": [{"index": c["index"], "name": c["name"], "duration": c["duration"], "kind": c.get("kind", "node")} for c in inspection["clips"]],
            "joints": inspection["joints"],
            "skinned": inspection["skins"] > 0,
            "form_hud_nodes": len(inspection["form_hud_nodes"]),
            "triangles": inspection["triangles"],
            "normalization": inspection["normalization"],
            "form": copy.deepcopy(record.get("form")),
            "inspector": inspection["inspector"],
        }
