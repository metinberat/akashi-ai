import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.absolute import AkashiCore, get_core
from app.core.config import Settings
from app.main import app

TOKEN = "core-api-test-token-0000000000000000"


class CoreApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.settings = Settings(
            ai_provider="mock",
            api_token=TOKEN,
            memory_file=root / "memory.json",
            long_term_memory_file=root / "long-term.json",
            task_file=root / "tasks.json",
            upload_dir=root / "uploads",
            file_index_file=root / "files.json",
            device_file=root / "devices.json",
            intelligence_file=root / "intelligence.json",
            schedule_file=root / "schedules.json",
        )
        self.core = AkashiCore(self.settings)
        app.dependency_overrides[get_core] = lambda: self.core
        self.addCleanup(app.dependency_overrides.clear)
        self.patcher = patch("app.core.auth.get_settings", return_value=self.settings)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {TOKEN}"}

    def test_existing_chat_contract_remains_stable(self) -> None:
        response = self.client.post(
            "/chat",
            headers=self.headers,
            json={"message": "Help me study physics", "session_id": "test", "mode": "private"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            set(payload),
            {"response", "session_id", "provider", "mode", "intent"},
        )
        self.assertEqual(payload["provider"], "mock")
        self.assertEqual(payload["intent"], "study")

    def test_memory_and_capabilities_endpoints(self) -> None:
        created = self.client.post(
            "/memory",
            headers=self.headers,
            json={"content": "Prefer concise answers", "category": "preference"},
        )
        self.assertEqual(created.status_code, 201)
        retrieved = self.client.post(
            "/memory/retrieve",
            headers=self.headers,
            json={"query": "concise answer"},
        )
        self.assertEqual(retrieved.status_code, 200)
        self.assertEqual(len(retrieved.json()["memories"]), 1)
        capabilities = self.client.get("/system/capabilities", headers=self.headers)
        self.assertEqual(capabilities.status_code, 200)
        self.assertTrue(capabilities.json()["features"]["tasks"])

        with patch("app.api.system._probe_json", new=AsyncMock(return_value=(False, None))), patch(
            "app.api.system._probe_research", new=AsyncMock(return_value=False)
        ):
            health = self.client.get("/system/health", headers=self.headers)
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["core"]["status"], "online")
        self.assertEqual(health.json()["auth"]["status"], "authorized")
        self.assertEqual(health.json()["model"]["status"], "mock")

    def test_private_conversations_can_be_listed_and_resumed(self) -> None:
        chat = self.client.post(
            "/chat",
            headers=self.headers,
            json={
                "message": "Plan the mobile product surface",
                "session_id": "mobile-product-session",
                "mode": "private",
            },
        )
        self.assertEqual(chat.status_code, 200)
        listing = self.client.get(
            "/memory/conversations",
            headers=self.headers,
        )
        self.assertEqual(listing.status_code, 200)
        item = listing.json()["conversations"][0]
        self.assertEqual(item["session_id"], "mobile-product-session")
        self.assertEqual(item["message_count"], 2)
        resumed = self.client.get(
            "/memory/conversations/mobile-product-session",
            headers=self.headers,
        )
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(len(resumed.json()["messages"]), 2)
        invalid = self.client.get(
            "/memory/conversations/not%20valid",
            headers=self.headers,
        )
        self.assertEqual(invalid.status_code, 422)

    def test_openapi_contains_old_and_new_routes(self) -> None:
        paths = self.client.get("/openapi.json").json()["paths"]
        for path in ("/health", "/chat", "/image/fast-test", "/memory", "/research", "/tasks", "/devices", "/intelligence/items", "/voice/sessions"):
            self.assertIn(path, paths)

    def test_body_limit_and_new_routes_fail_closed(self) -> None:
        response = self.client.post("/chat", content=b"{}", headers={"Content-Length": "999999999"})
        self.assertEqual(response.status_code, 413)
        for path in ("/memory", "/files", "/tasks", "/devices", "/tools", "/system/capabilities", "/system/health", "/events/stream", "/live/actions", "/intelligence/items", "/voice/sessions/unknown"):
            self.assertEqual(self.client.get(path).status_code, 401, path)

    def test_live_interaction_ids_are_validated(self) -> None:
        response = self.client.get(
            "/live/interactions/not valid",
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "Invalid interaction_id.")

    def test_vision_is_not_advertised_without_a_real_vision_model(self) -> None:
        response = self.client.post("/chat", headers=self.headers, json={"message": "Inspect image", "model_profile": "vision"})
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
