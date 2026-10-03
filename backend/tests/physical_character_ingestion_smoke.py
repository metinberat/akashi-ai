"""Short deterministic Blender -> fixed adapter -> V3 ingestion integration.

All assets are synthetic and local. No model inference or external assets.
Run from backend with PYTHONPATH=. .venv/Scripts/python tests/physical_character_ingestion_smoke.py
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from app.autonomy.knowledge import KnowledgeStore
from app.expertise.schema import Source
from app.expertise.service import CharacterExpertiseService
from app.expertise.store import ExpertiseStore

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "desktop" / "agent"))
from akashi_agent.actions import ActionExecutor
from akashi_agent.config import AgentSettings


def main():
    with tempfile.TemporaryDirectory(prefix="akashi-v3-synthetic-") as directory:
        root = Path(directory).resolve()
        executor = ActionExecutor(AgentSettings(token="synthetic-test-only", allowed_roots=(root,), capture_dir=root / "captures", credential_file=root / "credential"))
        blender = executor.apps.get("blender")
        if not blender:
            print(json.dumps({"status": "BLOCKED", "reason": "Blender not installed/discovered"}))
            return 2
        script = Path(__file__).parent / "fixtures" / "create_synthetic_blender.py"
        project, output = root / "synthetic.blend", root / "observed.json"
        child_env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "PATH", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA") if key in os.environ}
        created = subprocess.run([blender, "--disable-autoexec", "--background", "--factory-startup", "--python", str(script), "--", str(project)], shell=False, env=child_env, capture_output=True, timeout=90)
        if created.returncode != 0 or not project.is_file():
            raise RuntimeError("Synthetic Blender fixture creation failed.")
        result = executor.execute("blender_operation", {"operation": "inspect_character", "project": str(project), "output": str(output)}, approved=True)["data"]
        assert result["verified"] and result["joint_count"] == 2
        service = CharacterExpertiseService(ExpertiseStore(root / "expertise.sqlite3"), KnowledgeStore(root / "knowledge.json"))
        source = Source(reference="synthetic:blender-generated", category="synthetic_fixture", synthetic=True)
        asset = service.ingest("observed.json", output.read_bytes(), source)
        assert asset["analysis"]["observed"]["has_rig"]
        assert asset["analysis"]["computed"]["skin_metrics"][0]["mean_influences"] == 2
        assert asset["analysis"]["observed"]["has_animation"]
        assert service.ingest("observed.json", output.read_bytes(), source)["cache_hit"]
        export = root / "synthetic.glb"
        executor.execute("blender_operation", {"operation": "export_gltf", "project": str(project), "output": str(export)}, approved=True)
        glb_asset = service.ingest("synthetic.glb", export.read_bytes(), source)
        assert glb_asset["analysis"]["observed"]["has_skin"]
        assert service.dataset()["record_count"] == 0
        print(json.dumps({"status": "WORKING", "provenance": "synthetic", "blender_inspection": True, "glb_ingestion": True, "skin_metrics": True, "animation": True, "deduplication": True, "default_dataset_excludes_synthetic": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
