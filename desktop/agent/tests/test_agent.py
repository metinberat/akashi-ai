import tempfile
import unittest
import sys
import json
import hashlib
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path

from fastapi.testclient import TestClient

from akashi_agent.actions import ActionExecutor, action_risk
from akashi_agent.config import AgentSettings
from akashi_agent.main import app
import akashi_agent.main as agent_main
from akashi_agent.security import CredentialStore, PathPolicy


TOKEN = "agent-unit-test-token-000000000000000"


class AgentSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.settings = AgentSettings(
            token=TOKEN,
            allowed_roots=(self.root,),
            capture_dir=self.root / "captures",
            credential_file=self.root / "credential.bin",
        )
        self.executor = ActionExecutor(self.settings)

    def test_path_policy_blocks_traversal(self) -> None:
        allowed = self.root / "allowed.txt"
        allowed.write_text("safe", encoding="utf-8")
        policy = PathPolicy((self.root,))
        self.assertEqual(policy.resolve(str(allowed)), allowed)
        with self.assertRaises(PermissionError):
            policy.resolve(str(self.root.parent))

    def test_structured_actions_have_no_generic_shell_and_require_confirmation(self) -> None:
        self.assertNotIn("shell", self.executor.capabilities())
        self.assertNotIn("powershell", self.executor.capabilities())
        with self.assertRaises(ValueError):
            self.executor.execute("arbitrary_shell", {"command": "whoami"}, True)
        self.assertEqual(action_risk("take_screenshot"), "safe")
        self.assertEqual(action_risk("capture_camera_frame"), "safe")
        self.assertEqual(action_risk("launch_application"), "confirm")
        self.assertEqual(action_risk("get_desktop_state"), "safe")
        self.assertEqual(action_risk("computer_input"), "confirm")
        self.assertIn("capture_camera_frame", self.executor.capabilities())
        self.assertIn("window_control", self.executor.capabilities())
        self.assertIn("computer_input", self.executor.capabilities())
        self.assertIn("inspect_git", self.executor.capabilities())
        self.assertEqual(action_risk("browser_snapshot"), "safe")
        self.assertEqual(action_risk("browser_action"), "confirm")
        self.assertIn("browser_snapshot", self.executor.capabilities())
        self.assertIn("browser_action", self.executor.capabilities())
        self.assertEqual(action_risk("blender_operation"), "confirm")
        self.assertIn("blender_operation", self.executor.capabilities())

    def test_browser_actions_are_semantic_bounded_and_confirmed(self) -> None:
        with self.assertRaises(PermissionError):
            self.executor.execute("browser_action", {"operation": "click", "target": {"text": "Continue"}})
        with self.assertRaises(ValueError):
            self.executor.execute("browser_action", {"operation": "click", "target": {"script": "alert(1)"}}, approved=True)
        with self.assertRaises(ValueError):
            self.executor.execute("browser_start", {"url": "https://user:secret@example.com"}, approved=True)

    def test_blender_adapter_rejects_arbitrary_code_and_unapproved_paths(self) -> None:
        with self.assertRaises(PermissionError):
            self.executor.execute("blender_operation", {"operation": "inspect_scene", "project": str(self.root / "scene.blend")})
        with self.assertRaises(ValueError):
            self.executor.execute("blender_operation", {"operation": "python", "project": str(self.root / "scene.blend"), "code": "import os"}, approved=True)
        wrong = self.root / "scene.txt"
        wrong.write_text("not a blend", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.executor.execute("blender_operation", {"operation": "inspect_scene", "project": str(wrong)}, approved=True)

    def test_safe_file_metadata_stays_inside_roots(self) -> None:
        path = self.root / "notes.txt"
        path.write_text("AKASHI", encoding="utf-8")
        result = self.executor.execute("file_metadata", {"path": str(path)})
        self.assertEqual(result["data"]["name"], "notes.txt")

    def test_sensitive_paths_and_unexpected_arguments_are_blocked(self) -> None:
        secret = self.root / ".env"
        secret.write_text("fixture", encoding="utf-8")
        with self.assertRaises(PermissionError):
            self.executor.execute("file_metadata", {"path": str(secret)})
        with self.assertRaises(ValueError):
            self.executor.execute("get_system_status", {"command": "anything"})
        with self.assertRaises(ValueError):
            self.executor.execute("list_processes", {"limit": True})

    def test_project_scripts_disabled_without_local_registry(self) -> None:
        self.assertNotIn("run_project_script", self.executor.capabilities())
        with self.assertRaises(PermissionError):
            self.executor.execute("run_project_script", {"project": str(self.root), "script": "test"}, True)

    def test_directory_listing_omits_secret_files(self) -> None:
        (self.root / ".env").write_text("fixture")
        (self.root / "normal.txt").write_text("safe")
        result = self.executor.execute("list_directory", {"path": str(self.root)})
        self.assertEqual([item["name"] for item in result["data"]["entries"]], ["normal.txt"])

    def test_file_operations_are_bounded_confirmed_and_verified(self) -> None:
        destination = self.root / "created.txt"
        with self.assertRaises(PermissionError):
            self.executor.execute(
                "file_operation",
                {"operation": "create_text", "destination": str(destination), "content": "AKASHI"},
            )
        created = self.executor.execute(
            "file_operation",
            {"operation": "create_text", "destination": str(destination), "content": "AKASHI"},
            approved=True,
        )
        self.assertTrue(created["data"]["verified"])
        read = self.executor.execute("read_text_file", {"path": str(destination)})
        self.assertEqual(read["data"]["content"], "AKASHI")
        copied = self.root / "copied.txt"
        result = self.executor.execute(
            "file_operation",
            {"operation": "copy", "source": str(destination), "destination": str(copied)},
            approved=True,
        )
        self.assertTrue(result["data"]["verified"])

    def test_computer_input_is_typed_and_has_no_shell_escape(self) -> None:
        with self.assertRaises(PermissionError):
            self.executor.execute("computer_input", {"operation": "move", "x": 1, "y": 1})
        with self.assertRaises(ValueError):
            self.executor.execute("computer_input", {"operation": "shell", "text": "whoami"}, approved=True)
        with self.assertRaises(ValueError):
            self.executor.execute(
                "computer_input",
                {"operation": "shortcut", "keys": ["ctrl", "alt", "delete"]},
                approved=True,
            )

    @unittest.skipUnless(sys.platform == "win32", "Windows-native observation")
    def test_real_desktop_observation_returns_windows_and_bounds(self) -> None:
        result = self.executor.execute("get_desktop_state", {"limit": 20})
        state = result["data"]
        self.assertEqual(state["platform"], "windows")
        self.assertGreater(state["virtual_screen"]["width"], 0)
        self.assertIsInstance(state["windows"], list)

    def test_device_credential_round_trip_is_not_plaintext(self) -> None:
        store = CredentialStore(self.settings.credential_file)
        value = {"device_id": "device", "device_token": "highly-sensitive-test-token"}
        store.save(value)
        self.assertEqual(store.load(), value)
        if __import__("sys").platform == "win32":
            self.assertNotIn(b"highly-sensitive-test-token", self.settings.credential_file.read_bytes())

    def test_blender_patch_is_confirmed_fixed_and_non_overwriting(self):
        project, weights, output = self.root/"source.blend", self.root/"weights.json", self.root/"new.blend"
        project.write_bytes(b"synthetic-mock")
        weights.write_text("{}")
        self.executor.apps["blender"] = "allowlisted-blender.exe"
        arguments = {"operation": "apply_weights", "project": str(project), "patch": str(weights), "output": str(output)}
        with self.assertRaises(PermissionError):
            self.executor.execute("blender_operation", arguments)
        def run(command, **kwargs):
            self.assertFalse(kwargs["shell"])
            self.assertIn("--disable-autoexec", command)
            self.assertIn("--patch", command)
            self.assertNotIn("AKASHI_API_TOKEN", kwargs["env"])
            output.write_bytes(b"synthetic-mock-output")
            return SimpleNamespace(returncode=0, stdout="AKASHI_BLENDER_RESULT="+json.dumps({"verified": True}), stderr="")
        with patch("akashi_agent.actions.subprocess.run", side_effect=run):
            self.assertTrue(self.executor.execute("blender_operation", arguments, approved=True)["ok"])
        with self.assertRaises(ValueError):
            self.executor.execute("blender_operation", arguments, approved=True)
        self.assertEqual(project.read_bytes(), b"synthetic-mock")

    def test_blender_patch_cannot_reference_outside_approved_roots(self):
        project = self.root/"source.blend"
        project.write_bytes(b"synthetic-mock")
        self.executor.apps["blender"] = "allowlisted-blender.exe"
        with self.assertRaises(PermissionError):
            self.executor.execute("blender_operation", {"operation": "apply_weights", "project": str(project), "output": str(self.root/"new.blend"), "patch": str(self.root.parent/"outside.json")}, approved=True)

    def test_blender_weight_bridge_rejects_executable_patch_schema(self):
        from akashi_agent.blender_bridge import apply_weights
        payload = self.root/"bad.json"
        payload.write_text(json.dumps({"schema_version": 1, "script": "arbitrary Python", "patches": []}))
        with self.assertRaises(ValueError):
            apply_weights(None, payload, self.root/"new.blend")

    def test_character_patch_chunking_hash_replay_and_bounds(self):
        output = self.root/"patch.json"
        content = json.dumps({"schema_version": 1, "synthetic": True, "version_id": "synthetic-fixture-version", "patches": [{"mesh": "synthetic-mesh", "geometry_digest": "0"*64, "bones": {"j": "synthetic-bone"}, "weights": [{"j": 1}]*9000}]})
        chunks = [content[i:i+24000] for i in range(0, len(content), 24000)]
        digest = hashlib.sha256(content.encode()).hexdigest()
        def stage(index, chunk=None):
            return self.executor.execute("blender_operation", {"operation": "stage_weights", "output": str(output), "chunk": chunks[index] if chunk is None else chunk,
                "chunk_index": index, "chunk_count": len(chunks), "sha256": digest}, approved=True)["data"]
        self.assertFalse(stage(1)["complete"])
        self.assertFalse(stage(1)["complete"])
        with self.assertRaises(ValueError): stage(1, "tamper")
        self.assertFalse(stage(0)["complete"])
        for index in range(2, len(chunks)):
            result = stage(index)
        self.assertTrue(result["complete"])
        self.assertEqual(output.read_text(), content)
        with self.assertRaises(ValueError): stage(2)
        with self.assertRaises(ValueError):
            self.executor.execute("blender_operation", {"operation": "stage_weights", "output": str(self.root/"bad.json"), "chunk": "x"*24001,
                "chunk_index": 0, "chunk_count": 1, "sha256": digest}, approved=True)

    def test_character_patch_stage_rejects_wrong_final_hash(self):
        output = self.root/"bad-hash.json"
        with self.assertRaises(ValueError):
            self.executor.execute("blender_operation", {"operation": "stage_weights", "output": str(output), "chunk": '{"schema_version":1,"patches":[]}',
                "chunk_index": 0, "chunk_count": 1, "sha256": "0"*64}, approved=True)
        self.assertFalse(output.exists())

    def test_character_patch_staging_rejects_linked_internal_files(self):
        output = self.root/"linked-patch.json"
        content = '{"schema_version":1,"patches":[]}'
        digest = hashlib.sha256(content.encode()).hexdigest()
        identity = hashlib.sha256((str(output)+digest).encode()).hexdigest()[:24]
        staging = self.root/('.akashi-character-'+identity)
        staging.mkdir()
        original = self.root/"untouched.txt"
        original.write_text("preserve original")
        (staging/"part-0000").hardlink_to(original)
        with self.assertRaises(PermissionError):
            self.executor.execute("blender_operation", {"operation": "stage_weights", "output": str(output), "chunk": content,
                "chunk_index": 0, "chunk_count": 1, "sha256": digest}, approved=True)
        self.assertEqual(original.read_text(), "preserve original")
        self.assertFalse(output.exists())


class AgentApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original = agent_main.settings
        agent_main.settings = AgentSettings(
            token=TOKEN,
            allowed_roots=(Path(tempfile.gettempdir()).resolve(),),
            capture_dir=Path(tempfile.gettempdir()) / "akashi-test-captures",
            credential_file=Path(tempfile.gettempdir()) / "akashi-test-credential",
        )
        self.addCleanup(setattr, agent_main, "settings", self.original)
        self.client = TestClient(app)

    def test_health_is_public_and_actions_are_authenticated(self) -> None:
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/v1/capabilities").status_code, 401)
        response = self.client.get(
            "/v1/capabilities",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        self.assertEqual(response.status_code, 200)
        action_names = {item["name"] for item in response.json()["actions"]}
        self.assertNotIn("shell", action_names)


if __name__ == "__main__":
    unittest.main()
