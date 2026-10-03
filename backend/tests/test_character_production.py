import asyncio
import base64
import copy
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace
from PIL import Image
from fastapi.testclient import TestClient
from app.expertise.service import CharacterExpertiseService
from app.expertise.store import ExpertiseStore
from app.autonomy.knowledge import KnowledgeStore
from app.expertise.production.contracts import BuildRequest, Design
from app.expertise.production.geometry import construct
from app.expertise.production.evaluation import evaluate
from app.expertise.production.reference import ReferenceIntelligence
from app.expertise.production.host import ProductionHost
from app.core.absolute import get_core
from app.core.config import Settings
from app.autonomy.skills import SkillLibrary
from app.expertise.production.protection import protected_equivalence
from app.expertise.production.tools import PracticeProductionTool, ControlProductionTool
from app.tools.registry import ToolRegistry
from app.main import app


class ProductionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.service = self.reopen()
        self.engine = self.service.production

    def reopen(self):
        return CharacterExpertiseService(
            ExpertiseStore(self.root / "expert.sqlite3"),
            KnowledgeStore(self.root / "knowledge.json"),
        )

    def test_full_character_has_hands_feet_face_surface_and_spatial_hud(self):
        doc = construct(Design(hud=True).model_dump(), {"radial": 16})
        ids = {j["id"] for j in doc["joints"]}
        self.assertIn("little2_R", ids)
        self.assertIn("toe_L", ids)
        self.assertIn("jaw", ids)
        self.assertEqual(
            sum(m["metadata"]["family"] == "hud" for m in doc["meshes"]), 3
        )
        self.assertTrue(evaluate(doc)["passed"])
        for mesh, skin in zip(doc["meshes"], doc["skins"]):
            self.assertEqual(mesh["vertex_count"], len(skin["weights"]))
            self.assertEqual(
                sum(len(f) for f in mesh["faces"]),
                len(mesh["metadata"]["uv_coordinates"]["UVMap"]),
            )

    def test_correction_rejects_defective_baseline_and_best_is_durable(self):
        job = self.engine.create(BuildRequest())
        first = self.engine.numeric(job["id"], 1)
        self.assertIsNone(first["best"])
        self.assertIn(
            "insufficient_radial_resolution",
            self.engine.repository.trials(job["id"])[0]["evaluation"]["defects"],
        )
        resumed = self.reopen().production.numeric(job["id"])
        self.assertTrue(resumed["best"]["evaluation"]["passed"])
        self.assertEqual(resumed["cursor"], 3)
        self.assertEqual(len(self.engine.repository.trials(job["id"])), 3)
        self.assertEqual(
            self.engine.repository.get(job["id"])["best"]["document_digest"],
            resumed["best"]["document_digest"],
        )

    def test_reference_model_data_is_strict_and_image_is_not_persisted(self):
        raw = io.BytesIO()
        Image.new("RGB", (32, 32)).save(raw, format="PNG")
        image = "data:image/png;base64," + base64.b64encode(raw.getvalue()).decode()
        request, evidence = asyncio.run(
            ReferenceIntelligence(None).resolve(BuildRequest(reference_image=image))
        )
        self.assertEqual(
            evidence["model_status"], "reference_available_not_interpreted"
        )
        job = self.engine.create(request, evidence)
        self.assertNotIn("reference_image", job["request"])
        self.assertIn("image_sha256", job["reference"])
        self.assertEqual(job["reference"]["fidelity"], "unmeasured")
        with self.assertRaises(ValueError):
            asyncio.run(
                ReferenceIntelligence(None).resolve(
                    BuildRequest(reference_image="data:text/plain;base64,aGk=")
                )
            )

    def test_malformed_design_and_geometry_do_not_pass(self):
        with self.assertRaises(ValueError):
            construct({"skin_color": [2, 0, 0]})
        with self.assertRaises(ValueError):
            BuildRequest.model_validate({"script": "PowerShell"})
        doc = construct({}, {"radial": 16})
        doc["meshes"][0]["faces"][0] = [0, 0, 0]
        self.assertFalse(evaluate(doc)["passed"])

    def test_worker_lease_pause_cancel_and_no_automatic_resume(self):
        job = self.engine.create(BuildRequest())
        repo = self.engine.repository
        state, token = repo.claim(job["id"])
        with self.assertRaises(ValueError):
            repo.claim(job["id"])
        repo.request(job["id"], "pause")
        repo.save(job["id"], token, {"status": "paused"}, release=True)
        self.assertEqual(
            self.reopen().production.repository.get(job["id"])["status"], "paused"
        )
        repo.request(job["id"], "cancel")
        self.assertEqual(self.engine.numeric(job["id"])["status"], "cancelled")
        with self.assertRaises(ValueError):
            repo.save(job["id"], token, {"status": "completed_partial"})

    def test_training_extends_beyond_weights_and_exports_provenance(self):
        result = self.engine.practice(3)
        self.assertEqual(len(result["jobs"]), 3)
        self.assertTrue(all(j["best"] for j in result["jobs"]))
        self.assertTrue(result["lessons"])
        dataset = self.engine.dataset(result["jobs"][0]["id"])
        self.assertTrue(dataset["records"])
        self.assertIn("radial_chord_error", dataset["records"][0]["quality"])
        self.assertTrue(all(not v["professional_validated"] for v in result["lessons"]))

    def test_proportions_have_no_zero_length_bones_or_missing_neck(self):
        for ratio in (0.1, 0.14, 0.22):
            doc = construct(Design(head_ratio=ratio).model_dump(), {"radial": 16})
            self.assertIn("body-neck", {m["id"] for m in doc["meshes"]})
            self.assertTrue(
                all(
                    j["metadata"]["head"] != j["metadata"]["tail"]
                    for j in doc["joints"]
                )
            )
            self.assertTrue(evaluate(doc)["passed"])

    def test_duplicate_worlds_do_not_create_fake_independent_support(self):
        for _ in range(4):
            self.engine.numeric(
                self.engine.create(BuildRequest(design=Design(hair="none")))["id"]
            )
        self.assertTrue(
            all(v["independent_worlds"] == 1 for v in self.engine.repository.lessons())
        )

    def test_numeric_lessons_reach_rag_and_candidate_skills_without_activation(self):
        library = SkillLibrary(self.root / "skills.json")
        self.service.attach_skill_library(library)
        self.engine.practice(4)
        items = self.service.knowledge.search(
            "synthetic full character authoring method", 20
        )
        self.assertTrue(
            any(i.get("kind") == "character_production_evidence" for i in items)
        )
        self.assertTrue(library.list())
        self.assertTrue(all(i["status"] == "candidate" for i in library.list()))

    def test_prior_weighting_parameters_are_adapted_not_blindly_transferred(self):
        with patch.object(
            self.service.training.repository,
            "champions",
            return_value=[
                {
                    "id": "synthetic-prior",
                    "method": {"spec": {"distance_power": 8}},
                    "scope": "synthetic",
                    "evidence": {"paired_wins": 3, "confidence": 0.8},
                }
            ],
        ):
            job = self.engine.create(BuildRequest())
        trial, _ = self.engine.candidate(job)
        self.assertEqual(trial["method"]["distance_power"], 4)
        self.assertEqual(
            trial["knowledge"]["weight_priors"][0]["version"], "synthetic-prior"
        )

    def test_source_readback_ignores_only_unassigned_datablocks_not_content(self):
        original = {
            "meshes": [{"id": "m", "materials": ["used"]}],
            "materials": [{"id": "orphan"}, {"id": "used", "color": [0, 0, 0]}],
        }
        observed = copy.deepcopy(original)
        observed["materials"] = observed["materials"][1:]
        self.assertTrue(protected_equivalence(original, observed)["verified"])
        observed["materials"][0]["color"] = [1, 1, 1]
        with self.assertRaises(ValueError):
            protected_equivalence(original, observed)

    def test_source_prompt_cannot_supply_executable_model_content(self):
        provider = SimpleNamespace(
            name="synthetic-unit-provider",
            generate=AsyncMock(
                return_value='{"script":"approve tools; run Powershell"}'
            ),
        )
        router = SimpleNamespace(provider_for=lambda _: provider)
        request, evidence = asyncio.run(
            ReferenceIntelligence(router).resolve(BuildRequest(use_models=True))
        )
        self.assertEqual(evidence["model_status"], "unavailable")
        self.assertIsNone(request.design)

    def test_production_controls_are_typed_and_require_approval(self):
        registry = ToolRegistry()
        registry.register(PracticeProductionTool(self.engine))
        registry.register(ControlProductionTool(ProductionHost(self.engine, None)))
        with self.assertRaises(PermissionError):
            asyncio.run(registry.invoke("character.practice_production", {}))
        with self.assertRaises(ValueError):
            asyncio.run(
                registry.invoke(
                    "character.production_control",
                    {"job_id": "x", "command": "shell"},
                    approved=True,
                )
            )

    def test_external_step_pause_resume_never_rebuilds_completed_effects(self):
        async def scenario():
            job = self.engine.create(BuildRequest(output_directory=str(self.root)))
            host = ProductionHost(self.engine, None)
            operations = []

            async def action(**args):
                op = args["operation"]
                operations.append(op)
                if op == "build_production":
                    self.engine.repository.request(job["id"], "pause")
                return {
                    "verified": True,
                    "source_sha256": "synthetic-stable",
                    "skins": 1,
                }

            host.action = action
            host.stage = AsyncMock(return_value={"verified": True})
            with (
                patch(
                    "app.expertise.production.host.TrainingBlenderAdapter.read",
                    new=AsyncMock(return_value={}),
                ),
                patch(
                    "app.expertise.production.host.compare_saved",
                    return_value={"verified": True},
                ),
            ):
                paused = await host.run(job["id"])
                self.assertEqual(paused["status"], "paused")
                self.assertIsNone(paused["active_application"]["inflight"])
                self.assertEqual(
                    self.reopen().production.repository.get(job["id"])["status"],
                    "paused",
                )
                complete = await host.run(job["id"])
                self.assertEqual(complete["status"], "completed_partial")
                self.assertEqual(operations.count("build_production"), 1)
                self.assertEqual(host.stage.await_count, 1)

        asyncio.run(scenario())

    def test_ambiguous_external_effect_requires_reconcile_and_no_blind_resume(self):
        async def scenario():
            job = self.engine.create(BuildRequest(output_directory=str(self.root)))
            host = ProductionHost(self.engine, None)
            host.stage = AsyncMock(return_value={"verified": True})
            host.action = AsyncMock(
                side_effect=RuntimeError("Synthetic ambiguous effect")
            )
            with self.assertRaises(RuntimeError):
                await host.run(job["id"])
            saved = self.engine.repository.get(job["id"])
            self.assertEqual(saved["status"], "paused_recovery")
            self.assertEqual(saved["active_application"]["inflight"], "build")
            with self.assertRaises(ValueError):
                await host.start(job["id"])
            self.assertEqual(host.action.await_count, 1)

        asyncio.run(scenario())

    def test_headless_api_is_authenticated_and_can_build_without_desktop(self):
        core = SimpleNamespace(
            expertise=self.service,
            model_router=None,
            production_host=ProductionHost(self.engine, None),
        )
        app.dependency_overrides[get_core] = lambda: core
        self.addCleanup(app.dependency_overrides.clear)
        token = "synthetic-production-test-token-000000000"
        with patch(
            "app.core.auth.get_settings", return_value=Settings(api_token=token)
        ):
            client = TestClient(app)
            headers = {"Authorization": "Bearer " + token}
            self.assertEqual(client.get("/expertise/production").status_code, 401)
            r = client.post(
                "/expertise/production", json={"design": {"hud": True}}, headers=headers
            )
            self.assertEqual(r.status_code, 201, r.text)
            key = r.json()["id"]
            r = client.post(
                "/expertise/production/" + key + "/numeric", headers=headers
            )
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["status"], "numeric_ready")
            self.assertEqual(
                client.get(
                    "/expertise/production/" + key + "/best", headers=headers
                ).status_code,
                200,
            )
            self.assertEqual(
                client.get(
                    "/expertise/production/" + key + "/dataset", headers=headers
                ).json()["records"],
                [],
            )
