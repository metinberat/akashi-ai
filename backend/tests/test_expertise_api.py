import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient
from app.core.absolute import get_core
from app.core.config import Settings
from app.main import app
from app.autonomy.knowledge import KnowledgeStore
from app.expertise.service import CharacterExpertiseService
from app.expertise.store import ExpertiseStore
from tests.fixtures.characters import character
from tests.fixtures.workshop_characters import limb


class ExpertiseApiTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.expertise = CharacterExpertiseService(ExpertiseStore(root / "expertise.sqlite3"), KnowledgeStore(root / "knowledge.json"))
        core = SimpleNamespace(expertise=self.expertise, desktop=None, autonomy=SimpleNamespace(store=SimpleNamespace(get=lambda _id: None)))
        app.dependency_overrides[get_core] = lambda: core
        self.addCleanup(app.dependency_overrides.clear)
        self.token = "test-expertise-token-0000000000000000"
        auth = patch("app.core.auth.get_settings", return_value=Settings(api_token=self.token))
        auth.start()
        self.addCleanup(auth.stop)
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer " + self.token}
        self.source = {"reference": "synthetic:test", "category": "synthetic_fixture", "synthetic": True}

    def test_ingestion_inspection_compare_knowledge_and_export(self):
        created = self.client.post("/expertise/characters", headers=self.headers, json={"character": character("C"), "source": self.source})
        self.assertEqual(created.status_code, 201, created.text)
        identifier = created.json()["id"]
        self.assertEqual(self.client.get("/expertise/characters/" + identifier, headers=self.headers).status_code, 200)
        self.assertEqual(len(self.client.get("/expertise/characters", headers=self.headers).json()["characters"]), 1)
        comparison = self.client.post("/expertise/compare", headers=self.headers, json={"left": identifier, "right": identifier})
        self.assertEqual(comparison.json()["semantic_jaccard"], 1)
        knowledge = self.client.get("/expertise/knowledge?query=forearm%20twist", headers=self.headers).json()["knowledge"]
        item = next(item for item in knowledge if item["kind"] == "hypothesis")
        response = self.client.post("/expertise/knowledge/" + item["id"] + "/validate", headers=self.headers, json={"evidence_reference": "synthetic-test", "method": "manual test", "task_id": "missing"})
        self.assertEqual(response.status_code, 409)
        response = self.client.post("/expertise/knowledge/" + item["id"] + "/validate", headers=self.headers, json={"evidence_reference": "synthetic-test", "method": "manual test"})
        self.assertEqual(response.json()["validation_scope"], "synthetic_only")
        self.assertEqual(self.client.get("/expertise/dataset", headers=self.headers).json()["record_count"], 0)

    def test_headless_training_recipes_checkpoint_artifact_and_dataset(self):
        self.assertEqual(self.client.get("/expertise/training").status_code, 401)
        created = self.client.post("/expertise/characters", headers=self.headers, json={"character": limb(), "source": self.source}).json()
        recipe = self.client.get("/expertise/recipes/"+created["id"], headers=self.headers).json()
        self.assertEqual(recipe["historical_workflow"], "unknown")
        request = {"source_asset_ids": [created["id"]], "max_exercises": 2, "candidates_per_exercise": 4}
        value = self.client.post("/expertise/training", headers=self.headers, json=request)
        self.assertEqual(value.status_code, 201, value.text)
        run = value.json()
        base = "/expertise/training/"+run["id"]
        result = self.client.post(base+"/run", headers=self.headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["status"], "paused")
        exercises = self.client.get(base+"/exercises", headers=self.headers).json()["exercises"]
        self.assertEqual(len(exercises), 1)
        self.assertEqual(self.client.get(base+"/artifacts/"+exercises[0]["id"], headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get(base+"/dataset", headers=self.headers).json()["record_count"], 0)
        self.assertGreater(self.client.get(base+"/dataset?include_synthetic=true", headers=self.headers).json()["record_count"], 0)
        exported = self.client.get(base+"/dataset.jsonl?include_synthetic=true", headers=self.headers)
        self.assertTrue(all(json.loads(line)["synthetic"] for line in exported.text.splitlines()))
        self.assertEqual(self.client.post(base+"/run?exercises=10000", headers=self.headers).status_code, 422)
        self.assertEqual(self.client.post("/expertise/training", headers=self.headers, json={"command": "install"}).status_code, 422)
        self.assertEqual(self.client.post(base+"/cancel", headers=self.headers).json()["status"], "cancelled")

    def test_auth_upload_and_malformed_boundary(self):
        self.assertEqual(self.client.get("/expertise/characters").status_code, 401)
        self.assertEqual(self.client.post("/expertise/characters", json={}).status_code, 401)
        response = self.client.post("/expertise/characters/upload", headers=self.headers,
                                    files={"file": ("fixture.obj", b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3", "text/plain")}, data={"provenance": json.dumps(self.source)})
        self.assertEqual(response.status_code, 201, response.text)
        invalid = self.client.post("/expertise/characters/upload", headers=self.headers,
                                   files={"file": ("evil.fbx", b"unsupported", "application/octet-stream")}, data={"provenance": json.dumps(self.source)})
        self.assertEqual(invalid.status_code, 422)
        self.assertNotIn("traceback", invalid.text.lower())
        self.assertEqual(self.client.get("/openapi.json").status_code, 200)

    def test_workshop_routes_are_authenticated_durable_and_non_destructive(self):
        self.assertEqual(self.client.get("/expertise/workshops").status_code, 401)
        created = self.client.post("/expertise/characters", headers=self.headers, json={"character": limb(), "source": self.source}).json()
        response = self.client.post("/expertise/workshops", headers=self.headers, json={"asset_id": created["id"]})
        self.assertEqual(response.status_code, 201, response.text)
        job = response.json()
        run = self.client.post("/expertise/workshops/"+job["id"]+"/run?steps=1", headers=self.headers)
        self.assertEqual(run.status_code, 200, run.text)
        self.assertEqual(run.json()["status"], "paused")
        versions = self.client.get("/expertise/workshops/"+job["id"]+"/versions", headers=self.headers).json()["versions"]
        self.assertEqual(len(versions), 2)
        self.assertTrue(versions[-1]["decision"]["accepted"])
        self.assertEqual(self.client.get("/expertise/versions/"+run.json()["best_version"], headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get("/expertise/workshops/dataset", headers=self.headers).json()["record_count"], 0)
        self.assertEqual(self.client.get("/expertise/workshops/evidence", headers=self.headers).json()["evidence"], [])
        invalid = self.client.post("/expertise/workshops", headers=self.headers, json={"asset_id": created["id"], "proposals": [{"operation": "shell", "command": "whoami"}]})
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(self.client.get("/expertise/workshops/missing", headers=self.headers).status_code, 404)
        rolled = self.client.post("/expertise/workshops/"+job["id"]+"/rollback", headers=self.headers, json={"version_id": job["baseline_version"]})
        self.assertEqual(rolled.json()["best_version"], job["baseline_version"])
        self.assertEqual(self.client.post("/expertise/workshops/"+job["id"]+"/cancel", headers=self.headers).json()["status"], "cancelled")

    def test_refinement_route_requires_auth_and_bounded_explicit_request(self):
        route = "/expertise/workshops/synthetic-test/refine-blender"
        request = {"project": "C:/synthetic/source.blend", "output_directory": "C:/synthetic/output", "max_cycles": 2}
        self.assertEqual(self.client.post(route, json=request).status_code, 401)
        self.assertEqual(self.client.post(route, headers=self.headers, json={**request, "max_cycles": 100}).status_code, 422)
        self.assertEqual(self.client.post(route, headers=self.headers, json={**request, "max_cycles": True}).status_code, 422)
        with patch("app.expertise.blender_workflow.BlenderWorkshopWorkflow.refine", new_callable=AsyncMock) as refine:
            refine.return_value = {"status": "verified", "cycles": [], "synthetic_mock": True}
            self.assertEqual(self.client.post(route, headers=self.headers, json=request).status_code, 200)
            refine.assert_awaited_once_with("synthetic-test", request["project"], request["output_directory"], 2)
            refine.side_effect = RuntimeError("Synthetic transport failure.")
            self.assertEqual(self.client.post(route, headers=self.headers, json=request).status_code, 409)
