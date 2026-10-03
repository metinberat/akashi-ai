import asyncio
import base64
import io
import json
import os
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw
from app.expertise.production.geometry import construct
from app.expertise.production.evaluation import evaluate
from app.expertise.production.visual import analyze, compare, advise
from akashi_agent.production_contract import validate_production
from form_studio.engine import Providers
from form_studio.partner import Partner
import test_product


def reference(color=(45, 60, 90), alpha=True):
    image = Image.new(
        "RGBA", (96, 160), (0, 0, 0, 0) if alpha else (240, 240, 240, 255)
    )
    draw = ImageDraw.Draw(image)
    draw.ellipse((32, 8, 64, 40), fill=(*color, 255))
    draw.rectangle((24, 40, 72, 132), fill=(*color, 255))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


class LocalMeasurements(unittest.TestCase):
    def test_partial_foreground_is_rejected_and_valid_mask_is_trimmed(self):
        from form_studio.shape_worker import apply_foreground, ReferenceForegroundError

        image = Image.new("RGBA", (100, 100), (30, 40, 50, 255))
        mask = Image.new("L", image.size, 0)
        draw = ImageDraw.Draw(mask)
        draw.rectangle((45, 10, 55, 30), fill=255)
        with self.assertRaises(ReferenceForegroundError):
            apply_foreground(image, mask)
        draw.rectangle((25, 10, 75, 90), fill=255)
        result, fraction = apply_foreground(image, mask)
        self.assertGreater(fraction, 0.15)
        self.assertEqual(result.size, (51, 81))

    def test_identity_and_changed_palette(self):
        raw = reference()
        observed = analyze(raw)
        self.assertEqual(observed["mask_status"], "measured")
        self.assertEqual(observed["palette_scope"], "foreground")
        self.assertAlmostEqual(compare(raw, raw)["loss"], 0)
        self.assertGreater(compare(raw, reference((220, 40, 40)))["loss"], 0.01)
        self.assertEqual(compare(raw, raw)["professional_quality"], "unmeasured")

    def test_complex_background_abstains(self):
        image = Image.new("RGB", (64, 64))
        image.putdata(
            [((i * 37) % 256, (i * 71) % 256, (i * 97) % 256) for i in range(4096)]
        )
        out = io.BytesIO()
        image.save(out, format="PNG")
        self.assertEqual(
            analyze(out.getvalue())["palette_scope"], "whole_image_not_character"
        )
        result = compare(reference(), out.getvalue())
        self.assertIsNone(result["loss"])
        self.assertEqual(result["status"], "not_comparable")

    def test_advisor_does_not_require_external_models(self):
        value = advise("Exact photoreal cinematic face and hair with HUD")
        self.assertTrue(value["optional_specialist_recommended"])
        self.assertTrue(value["local_can_continue"])
        self.assertIn("professional", value["tier"])

    def test_atelier_preserves_rig_and_closed_geometry(self):
        classic = construct({}, {"radial": 24})
        atelier = construct(
            {"appearance": "atelier", "hair": "long", "hud": True}, {"radial": 24}
        )
        self.assertEqual(classic["joints"], atelier["joints"])
        self.assertEqual(len(atelier["joints"]), 57)
        self.assertTrue(evaluate(atelier)["passed"])
        validate_production(atelier)
        meshes = {m["id"]: m for m in atelier["meshes"]}
        self.assertIn("lid-L-True", meshes)
        self.assertIn("lapel-L", meshes)
        self.assertIn("hair-scalp", meshes)
        # Long back locks cannot descend over the middle of the mouth/chin.
        for m in atelier["meshes"]:
            if m["id"].startswith("hair-lock"):
                self.assertFalse(
                    any(
                        abs(x) < 0.03 and y < -0.05 and z < 1.65
                        for x, y, z in m["positions"]
                    )
                )

    def test_old_process_contract_and_unknown_profile(self):
        doc = construct({})
        del doc["metadata"]["production_design"]["appearance"]
        validate_production(doc)
        doc["metadata"]["production_design"]["appearance"] = "execute_script"
        with self.assertRaises(ValueError):
            validate_production(doc)

    def test_external_adapter_default_denied(self):
        with patch.dict(
            os.environ,
            {
                "FORM_VISION_PROVIDER": "gemini",
                "FORM_VISION_MODEL": "example",
                "FORM_EXTERNAL_MODELS_ENABLED": "false",
            },
        ):
            with self.assertRaises(ValueError):
                Providers().provider_for("vision")

    def test_local_reasoning_receives_measurements_not_fake_vision(self):
        class Provider:
            async def generate(self, payload, *args):
                value = json.loads(payload)
                assert value["local_reference_data"]["mask_status"] == "measured"
                return json.dumps(
                    {
                        "text": "A local measured palette is available; no semantic vision was used.",
                        "intent": "discussion",
                        "design": None,
                    }
                )

        class Router:
            def provider_for(self, capability):
                if capability == "vision":
                    raise ValueError("No local vision model")
                return Provider()

        image = "data:image/png;base64," + base64.b64encode(reference()).decode()
        _, evidence = asyncio.run(
            Partner(Router()).respond(
                {"project": {"design": {}}}, "Inspect", image, True
            )
        )
        self.assertFalse(evidence["image_model_used"])
        self.assertEqual(evidence["model_status"], "interpreted")


class QualityProductTests(test_product.ProductTests):
    def test_output_quarantine_survives_job_history_pruning(self):
        import hashlib

        engine = self.app.state.engine
        raw = json.dumps(construct({})).encode()
        digest = hashlib.sha256(raw).hexdigest()
        engine.projects.quarantine(digest, "restricted_shape")
        engine.projects.update(self.key, {"shape_jobs": []})
        result = self.client.post(
            self.base + "/uploads",
            files={"file": ("renamed.json", raw)},
            data={"synthetic": "true"},
        )
        self.assertEqual(result.status_code, 409)
        self.assertTrue(engine.projects.quarantined(digest))
        self.assertFalse(engine.projects.links(self.key, "asset"))

    def test_resume_cannot_bypass_active_compute_owner(self):
        from app.expertise.production.contracts import BuildRequest
        from types import SimpleNamespace

        engine = self.app.state.engine
        run = engine.domain.production.create(BuildRequest())
        engine.projects.link(self.key, "production", run["id"])
        engine.shape.worker = SimpleNamespace(done=lambda: False)
        try:
            response = self.client.post(self.base + "/runs/" + run["id"] + "/resume")
            self.assertEqual(response.status_code, 409)
            self.assertIsNone(engine.production.worker)
            with self.assertRaises(ValueError):
                engine.require_compute_available()
        finally:
            engine.shape.worker = None

    def test_shape_requires_operator_configuration_not_client_paths(self):
        upload = self.client.post(
            self.base + "/uploads", files={"file": ("synthetic.png", reference())}
        ).json()
        response = self.client.post(
            self.base + "/shape",
            json={"reference_id": upload["id"], "python": "cmd.exe"},
        )
        self.assertEqual(response.status_code, 422)
        with patch.dict(os.environ, {"FORM_LOCAL_SHAPE_ENABLED": "false"}):
            response = self.client.post(
                self.base + "/shape", json={"reference_id": upload["id"]}
            )
        self.assertEqual(response.status_code, 409)
        self.assertFalse(self.app.state.engine.shape.worker)

    def test_known_restricted_shape_cannot_be_ingested_as_learning_data(self):
        import hashlib

        engine = self.app.state.engine
        raw = json.dumps(construct({})).encode()
        engine.projects.update(
            self.key,
            {
                "shape_jobs": [
                    {
                        "id": "test-quarantine",
                        "status": "completed_partial",
                        "evidence": {"output_sha256": hashlib.sha256(raw).hexdigest()},
                    }
                ]
            },
        )
        result = self.client.post(
            self.base + "/uploads",
            files={"file": ("renamed.json", raw)},
            data={"synthetic": "true"},
        )
        self.assertEqual(result.status_code, 409)
        self.assertFalse(engine.projects.links(self.key, "asset"))

    def test_local_reference_proposal_without_any_model(self):
        upload = self.client.post(
            self.base + "/uploads", files={"file": ("synthetic.png", reference())}
        )
        self.assertEqual(upload.status_code, 200)
        with patch.object(
            self.app.state.engine.partner.providers,
            "provider_for",
            side_effect=AssertionError("Must not call a model"),
        ):
            response = self.client.post(
                self.base + "/messages",
                json={
                    "text": "Create a professional reference character",
                    "use_models": False,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["evidence"]["local_observations"]["mask_status"], "measured"
        )
        self.assertTrue(
            response.json()["evidence"]["capability_advisor"]["local_can_continue"]
        )
        snapshot = self.client.get(self.base).json()
        self.assertEqual(snapshot["project"]["design"]["appearance"], "atelier")
        self.assertFalse(snapshot["runs"])

    def test_unverified_visual_result_rejected(self):
        record = self.client.post(
            self.base + "/uploads", files={"file": ("synthetic.png", reference())}
        ).json()
        engine = self.app.state.engine
        from app.expertise.production.contracts import BuildRequest

        run = engine.domain.production.create(BuildRequest())
        engine.projects.link(self.key, "production", run["id"])
        result = self.client.post(
            self.base + "/visual/assess",
            json={"reference_id": record["id"], "run_id": run["id"]},
        )
        self.assertEqual(result.status_code, 409)
        self.assertFalse(engine.projects.get(self.key).get("visual_evaluations"))

    def test_visual_restart_marks_interrupted_no_recording_or_replay(self):
        engine = self.app.state.engine
        engine.projects.update(
            self.key, {"visual_lab": {"status": "running", "pending_run": "saved-id"}}
        )
        engine.recover()
        lab = engine.projects.get(self.key)["visual_lab"]
        self.assertEqual(lab["status"], "paused_recovery")
        self.assertEqual(lab["pending_run"], "saved-id")
        self.assertIsNone(engine.appearance.worker)
