"""Spatial Lab through AKASHI's real HTTP surface: /spatial, /tools and /chat."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.absolute import AkashiCore, get_core
from app.core.config import Settings
from app.main import app
from app.spatial.fixtures import build_glb

TOKEN = "spatial-api-test-token-000000000000000"


class SpatialApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.settings = Settings(
            ai_provider="mock", api_token=TOKEN, memory_file=root / "memory.json", long_term_memory_file=root / "lt.json",
            task_file=root / "tasks.json", upload_dir=root / "uploads", file_index_file=root / "files.json",
            device_file=root / "devices.json", intelligence_file=root / "intel.json", schedule_file=root / "schedules.json",
            phone_calls_file=root / "phone.json", autonomy_state_file=root / "autonomy.json",
            autonomy_knowledge_file=root / "knowledge.json", autonomy_skill_file=root / "skills.json",
            expertise_db=root / "expertise.sqlite3", live_state_file=root / "live.json",
            computer_state_file=root / "computer.json", voice_state_file=root / "voice.json",
            spatial_dir=root / "spatial", spatial_form_data_dir=root / "no-form",
        )
        self.root = root
        self.core = AkashiCore(self.settings)
        app.dependency_overrides[get_core] = lambda: self.core
        self.addCleanup(app.dependency_overrides.clear)
        patcher = patch("app.core.auth.get_settings", return_value=self.settings)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {TOKEN}"}

    def post(self, path, body=None, **kwargs):
        return self.client.post(path, headers=self.headers, json=body, **kwargs)

    def session(self):
        response = self.post("/spatial/sessions", {"label": "API"})
        self.assertEqual(response.status_code, 201)
        return response.json()["session"]["id"]

    def test_authentication_is_required(self):
        self.assertEqual(self.client.get("/spatial/capabilities").status_code, 401)

    def test_capabilities_are_honest_about_scope(self):
        body = self.client.get("/spatial/capabilities", headers=self.headers).json()
        self.assertIn("No depth reconstruction", body["scope"]["spatial_model"])
        self.assertFalse(body["form"]["available"])
        self.assertIn("object.transform", body["request_types"])

    def test_upload_command_poll_events_and_replay(self):
        session_id = self.session()
        upload = self.client.post("/spatial/assets", headers=self.headers,
                                  files={"file": ("Robot.glb", build_glb(skinned=True, clips=("Walk",)), "model/gltf-binary")})
        self.assertEqual(upload.status_code, 201, upload.text)
        asset_id = upload.json()["asset_id"]
        content = self.client.get(f"/spatial/assets/{asset_id}/content", headers=self.headers)
        self.assertEqual((content.status_code, content.headers["content-type"]), (200, "model/gltf-binary"))
        added = self.post(f"/spatial/sessions/{session_id}/commands", {"request": {"type": "scene.add_asset", "asset_id": asset_id}})
        self.assertEqual(added.status_code, 200, added.text)
        revision = added.json()["snapshot"]["session"]["revision"]
        unchanged = self.client.get(f"/spatial/sessions/{session_id}?since={revision}&client=true", headers=self.headers).json()
        self.assertFalse(unchanged["changed"])
        said = self.post(f"/spatial/sessions/{session_id}/interpret", {"text": "play the walking animation"}).json()
        self.assertEqual(said["snapshot"]["state"]["objects"][said["results"][0]["targets"][0]]["animation"]["clip"], "Walk")
        events = self.client.get(f"/spatial/sessions/{session_id}/events", headers=self.headers).json()
        self.assertEqual([e["seq"] for e in events["events"]], [1, 2, 3])
        self.assertEqual(events["events"][2]["origin"]["kind"], "language")
        self.assertIsNotNone(events["initial_state"])
        verified = self.post(f"/spatial/sessions/{session_id}/replay/verify").json()
        self.assertTrue(verified["verified"] and verified["matches_live_state"])
        at_one = self.client.get(f"/spatial/sessions/{session_id}/states/1", headers=self.headers).json()
        self.assertEqual(len(at_one["state"]["objects"]), 1)
        self.assertEqual(self.client.get(f"/spatial/sessions/{session_id}/states/99", headers=self.headers).status_code, 404)

    def test_errors_are_structured(self):
        session_id = self.session()
        bad = self.post(f"/spatial/sessions/{session_id}/commands", {"request": {"type": "object.fly"}})
        self.assertEqual((bad.status_code, bad.json()["code"]), (422, "invalid_request"))
        missing = self.post(f"/spatial/sessions/{session_id}/commands",
                            {"request": {"type": "object.transform", "target": {"ref": "selected"}, "mode": "reset"}})
        self.assertEqual(missing.status_code, 409)
        self.assertEqual(missing.json()["kind"], "clarification")
        self.assertEqual(self.client.get("/spatial/sessions/spatial-0000000000000000", headers=self.headers).status_code, 404)
        self.assertEqual(self.client.get("/spatial/sessions/..%2F..%2Fetc", headers=self.headers).status_code, 404)
        form = self.post(f"/spatial/sessions/{session_id}/commands", {"request": {"type": "scene.add_asset", "form": {"version": "latest"}}})
        self.assertEqual(form.json()["code"], "form_not_found")

    def test_lease_conflict_surfaces_as_409_for_voice(self):
        session_id = self.session()
        added = self.post(f"/spatial/sessions/{session_id}/commands", {"request": {"type": "scene.add_asset", "fixture": "calibration"}}).json()
        object_id = added["targets"][0]
        lease = self.post(f"/spatial/sessions/{session_id}/leases", {"object_id": object_id}).json()
        busy = self.post(f"/spatial/sessions/{session_id}/commands",
                         {"request": {"type": "object.transform", "target": {"id": object_id}, "mode": "scale", "factor": 2}})
        self.assertEqual((busy.status_code, busy.json()["code"]), (409, "object_busy"))
        commit = self.post(f"/spatial/sessions/{session_id}/commands", {
            "request": {"type": "object.transform", "target": {"id": object_id}, "mode": "set", "lease_id": lease["id"],
                        "transform": {"position": [0.4, 0.1, 0], "rotation": [0, 0, 0, 1], "scale": 1.1}},
            "origin": {"kind": "gesture", "provider": "mediapipe-hands", "input": {"gesture": "one_hand_move", "duration_ms": 640}}})
        self.assertEqual(commit.status_code, 200, commit.text)
        self.assertEqual(commit.json()["snapshot"]["session"]["leases"], [])

    def test_presence_over_http_resolves_hand_anchor_commands(self):
        session_id = self.session()
        self.post(f"/spatial/sessions/{session_id}/commands", {"request": {"type": "scene.add_asset", "fixture": "calibration"}})
        bad = self.post(f"/spatial/sessions/{session_id}/presence", {"anchors": {"right_hand": {"position": [0, 1], "confidence": 2}}})
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(self.client.put(f"/spatial/sessions/{session_id}/presence", headers=self.headers, json={"anchors": {}}).status_code, 405)
        sent = self.post(f"/spatial/sessions/{session_id}/presence", {"anchors": {"right_hand": {"position": [0.7, 1.2, 0.0], "confidence": 0.9}}})
        self.assertEqual(sent.status_code, 200)
        moved = self.post(f"/spatial/sessions/{session_id}/interpret", {"text": "Move that character to my right hand."}).json()
        object_id = moved["results"][0]["targets"][0]
        self.assertEqual(moved["snapshot"]["state"]["objects"][object_id]["transform"]["position"], [0.7, 1.2, 0.0])
        self.assertTrue(moved["snapshot"]["session"]["presence_fresh"])

    def test_chat_routes_to_open_spatial_lab_and_only_when_open(self):
        chat = {"message": "make it bigger", "session_id": "spatial-chat", "mode": "private"}
        response = self.post("/chat", chat).json()
        self.assertEqual(response["provider"], "mock")  # no open Spatial Lab: ordinary chat
        session_id = self.session()
        self.post(f"/spatial/sessions/{session_id}/commands", {"request": {"type": "scene.add_asset", "fixture": "calibration"}})
        self.client.get(f"/spatial/sessions/{session_id}?client=true", headers=self.headers)
        response = self.post("/chat", chat).json()
        self.assertEqual(response["provider"], "spatial-lab")
        self.assertIn("1.25", response["response"])
        response = self.post("/chat", {**chat, "message": "İskeleti göster"}).json()
        self.assertEqual(response["provider"], "spatial-lab")
        self.assertIn("iskelet", response["response"])
        response = self.post("/chat", {**chat, "message": "Explain quantum tunnelling briefly"}).json()
        self.assertEqual(response["provider"], "mock")

    def test_tools_registry_exposes_scene_bounded_tools_with_confirm_gate(self):
        session_id = self.session()
        tools = {t["name"]: t["risk"] for t in self.client.get("/tools", headers=self.headers).json()["tools"]}
        self.assertEqual(tools["spatial.command"], "safe")
        self.assertEqual(tools["spatial.confirm"], "confirm")
        invoked = self.post("/tools/spatial.command/invoke", {"arguments": {"session_id": session_id,
                            "request": {"type": "scene.add_asset", "fixture": "calibration"}}}).json()
        object_id = invoked["data"]["targets"][0]
        removal = self.post("/tools/spatial.command/invoke", {"arguments": {"session_id": session_id,
                            "request": {"type": "scene.remove", "target": {"id": object_id}}}}).json()
        token = removal["data"]["token"]
        denied = self.post("/tools/spatial.confirm/invoke", {"arguments": {"session_id": session_id, "token": token}})
        self.assertEqual(denied.status_code, 409)  # requires explicit approval
        approved = self.post("/tools/spatial.confirm/invoke", {"arguments": {"session_id": session_id, "token": token}, "approved": True})
        self.assertEqual(approved.json()["data"]["status"], "applied")
        scene = self.post("/tools/spatial.scene/invoke", {"arguments": {"session_id": session_id}}).json()
        self.assertEqual(scene["data"]["scene"]["objects"], [])

    def test_persistence_restart_and_corruption_fail_closed(self):
        session_id = self.session()
        self.post(f"/spatial/sessions/{session_id}/commands", {"request": {"type": "scene.add_asset", "fixture": "calibration"}})
        self.post(f"/spatial/sessions/{session_id}/interpret", {"text": "rotate it 90 degrees"})
        digest = self.client.get(f"/spatial/sessions/{session_id}", headers=self.headers).json()["session"]["digest"]
        restarted = AkashiCore(self.settings)
        app.dependency_overrides[get_core] = lambda: restarted
        restored = self.client.get(f"/spatial/sessions/{session_id}", headers=self.headers).json()
        self.assertEqual(restored["session"]["digest"], digest)
        undo = self.post(f"/spatial/sessions/{session_id}/commands", {"request": {"type": "history.undo"}})
        self.assertEqual(undo.status_code, 200)
        events = self.root / "spatial" / "sessions" / session_id / "events.jsonl"
        lines = events.read_text().splitlines()
        tampered = json.loads(lines[2])
        self.assertEqual(tampered["command"]["type"], "object.transform")
        tampered["command"]["transform"]["scale"] = 9.0
        lines[2] = json.dumps(tampered)
        events.write_text("\n".join(lines) + "\n")
        fresh = AkashiCore(self.settings)
        app.dependency_overrides[get_core] = lambda: fresh
        corrupted = self.client.get(f"/spatial/sessions/{session_id}", headers=self.headers)
        self.assertEqual((corrupted.status_code, corrupted.json()["code"]), (423, "session_corrupted"))
        listed = self.client.get("/spatial/sessions", headers=self.headers).json()["sessions"]
        self.assertIn(session_id, [s["id"] for s in listed])


if __name__ == "__main__":
    unittest.main()
