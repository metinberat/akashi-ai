import tempfile
import unittest
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
        self.assertIn("capture_camera_frame", self.executor.capabilities())

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

    def test_device_credential_round_trip_is_not_plaintext(self) -> None:
        store = CredentialStore(self.settings.credential_file)
        value = {"device_id": "device", "device_token": "highly-sensitive-test-token"}
        store.save(value)
        self.assertEqual(store.load(), value)
        if __import__("sys").platform == "win32":
            self.assertNotIn(b"highly-sensitive-test-token", self.settings.credential_file.read_bytes())


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
