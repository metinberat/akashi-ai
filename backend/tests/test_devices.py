import json
import tempfile
import unittest
from pathlib import Path

from app.devices.store import DeviceStore


class DevicePairingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "devices.json"
        self.store = DeviceStore(self.path, code_ttl=600, online_ttl=75)

    def test_pairing_hashes_token_and_enforces_action_approval(self) -> None:
        code = self.store.create_pairing_code()["code"]
        device, token = self.store.pair(
            code,
            "Test PC",
            "windows-desktop",
            ["get_system_status", "launch_application"],
        )
        self.assertIsNotNone(self.store.authenticate(device["id"], token))
        document = self.path.read_text(encoding="utf-8")
        self.assertNotIn(token, document)
        self.assertNotIn(code, document)
        with self.assertRaises(PermissionError):
            self.store.queue_action(device["id"], "launch_application", {"application": "vscode"}, False)
        action = self.store.queue_action(device["id"], "get_system_status", {}, False)
        polled = self.store.poll_actions(device["id"])
        self.assertEqual(polled[0]["id"], action["id"])
        completed = self.store.complete_action(device["id"], action["id"], True, {"cpu": 10}, None)
        self.assertEqual(completed["status"], "completed")

    def test_restricted_or_unadvertised_actions_are_rejected(self) -> None:
        code = self.store.create_pairing_code()["code"]
        device, _ = self.store.pair(code, "PC", "desktop", ["get_system_status"])
        with self.assertRaises(ValueError):
            self.store.queue_action(device["id"], "arbitrary_shell", {}, True)
        with self.assertRaises(ValueError):
            self.store.queue_action(device["id"], "find_file", {}, False)


if __name__ == "__main__":
    unittest.main()
