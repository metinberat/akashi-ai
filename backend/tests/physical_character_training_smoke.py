"""Short actual authenticated Agent → Blender self-training integration. Synthetic only."""
import asyncio
import json
import os
import subprocess
import uuid
from pathlib import Path

from app.autonomy.knowledge import KnowledgeStore
from app.expertise.schema import Source
from app.expertise.service import CharacterExpertiseService
from app.expertise.store import ExpertiseStore
from app.expertise.training.contracts import TrainingRequest
from app.expertise.training.blender import TrainingBlenderAdapter
from app.expertise.training.synthetic import generate
from tests.physical_character_workshop_smoke import isolated_http_agent
from akashi_agent.actions import ActionExecutor
from akashi_agent.config import AgentSettings


async def main():
    root = (Path("data/private/self-training-validation")/uuid.uuid4().hex[:12]).resolve()
    root.mkdir(parents=True)
    service = CharacterExpertiseService(ExpertiseStore(root/"expertise.sqlite3"), KnowledgeStore(root/"knowledge.json"))
    source = Source(reference="synthetic:procedural-character-production", category="synthetic_fixture", synthetic=True)
    asset = service.ingest("synthetic.json", json.dumps(generate(991,3)[1]).encode(), source)
    job = service.training.create(TrainingRequest(source_asset_ids=[asset["id"]], seed=591, start_level=3, max_level=3, max_exercises=4, candidates_per_exercise=8))
    result = await asyncio.to_thread(service.training.run, job["id"], 4)
    exercises = service.training.repository.exercises(job["id"])
    exercise = next(e for e in exercises if e["partition"] != "test" and e["best_evaluation"]["passed"])
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "PATH", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA") if key in os.environ}
    async with isolated_http_agent(root, env) as gateway:
        adapter = TrainingBlenderAdapter(gateway, service)
        evidence = await adapter.materialize(job["id"], exercise["id"], str(root))
        ingested = await adapter.ingest_blender(evidence["paths"]["blend"], str(root), source)
        assert ingested["analysis"]["observed"]["has_rig"]
        assert ingested["source"]["synthetic"]
        assert ingested["normalized"]["metadata"]["original_application_source_sha256"]
        assert all(m["metadata"].get("uv_coordinates") for m in ingested["normalized"]["meshes"])
        rich_project = root/"SYNTHETIC-rich-recipe.blend"
        executor = ActionExecutor(AgentSettings(token="synthetic-test-only", allowed_roots=(root,), capture_dir=root/"captures", credential_file=root/"credential"))
        fixture = Path(__file__).parent/"fixtures"/"create_recipe_blender.py"
        child = await asyncio.to_thread(subprocess.run, [executor.apps["blender"], "--disable-autoexec", "--background", evidence["paths"]["blend"],
            "--python", str(fixture.resolve()), "--", str(rich_project)], capture_output=True, timeout=90, shell=False, env=env)
        if child.returncode or not rich_project.is_file():
            raise RuntimeError("Synthetic rich-fixture creation failed: "+(child.stdout+child.stderr).decode(errors="replace")[-1200:])
        rich = await adapter.ingest_blender(str(rich_project), str(root), source)
        observed = rich["normalized"]
        assert any(m["metadata"].get("shape_key_data") for m in observed["meshes"])
        assert any(j["constraints"] for j in observed["joints"])
        assert any(m.get("shader_links") for m in observed["materials"])
        assert observed["animations"] and observed["animations"][0]["channels"][0]["handles_left"]
        assert observed["metadata"]["drivers"]
    # Restart does not start a worker, and immutable accepted state remains available.
    reopened = CharacterExpertiseService(ExpertiseStore(root/"expertise.sqlite3"), KnowledgeStore(root/"knowledge.json"))
    assert reopened.training.repository.get(job["id"])["status"] == "completed"
    assert reopened.training.repository.document(exercise["best_digest"])
    report = {"synthetic": True, "professional_asset_analyzed": False, "status": "WORKING", "run_id": job["id"],
        "exercises": result["completed_exercises"], "attempts": len(service.training.repository.attempts(job["id"])),
        "baseline_loss": exercise["baseline_evaluation"]["loss"], "best_loss": exercise["best_evaluation"]["loss"],
        "saved_readback": evidence["readback"], "application_poses": evidence["deformation"]["poses"], "paths": evidence["paths"],
        "deep_ingestion_asset": ingested["id"], "recipe": service.recipes.for_asset(ingested["id"])["id"],
        "rich_synthetic_ingestion": {"asset": rich["id"], "shape_keys": True, "constraint_parameters": True, "shader_links": True, "animation_handles": True, "shape_key_drivers": True},
        "auth": "real_loopback_agent; unauthenticated requests rejected", "restart_checkpoint": True,
        "limits": "procedural character structures; not professional artistic rig/face/animation mastery"}
    (root/"report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    asyncio.run(main())
