import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import app

TEST_TOKEN = "test-token-for-unit-tests-only-00000000"


class AuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.settings = Settings(api_token=TEST_TOKEN)
        self.patcher = patch("app.core.auth.get_settings", return_value=self.settings)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_health_and_docs_remain_public(self) -> None:
        for path in ("/health", "/docs", "/openapi.json"):
            self.assertEqual(self.client.get(path).status_code, 200)

    def test_missing_or_invalid_token_is_rejected(self) -> None:
        for method, path in (("get", "/auth/check"), ("post", "/chat"), ("get", "/live/actions"),
                             ("get", "/image/view?filename=x.png"),
                             ("post", "/image/fast-test")):
            for headers in ({}, {"Authorization": "Bearer wrong"},
                            {"Authorization": f"Basic {TEST_TOKEN}"}):
                response = getattr(self.client, method)(path, headers=headers)
                self.assertEqual(response.status_code, 401, (method, path, headers))
                self.assertEqual(response.headers.get("www-authenticate"), "Bearer")

        for path in (
            "/memory",
            "/research/status",
            "/tools",
            "/tasks",
            "/files",
            "/devices",
            "/events/stream",
            "/events/recent",
            "/system/capabilities",
            "/system/health",
            "/intelligence/items",
            "/voice/sessions/unknown",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401, path)

    def test_correct_token_passes_auth_probe(self) -> None:
        response = self.client.get("/auth/check", headers={"Authorization": f"Bearer {TEST_TOKEN}"})
        self.assertEqual(response.status_code, 200)

    def test_correct_token_reaches_existing_route_validation(self) -> None:
        headers = {"Authorization": f"Bearer {TEST_TOKEN}"}
        self.assertEqual(self.client.post("/chat", json={}, headers=headers).status_code, 422)
        self.assertEqual(self.client.get("/image/view", headers=headers).status_code, 422)

    def test_unconfigured_server_fails_closed(self) -> None:
        with patch("app.core.auth.get_settings", return_value=Settings(api_token=None)):
            response = self.client.get("/auth/check")
        self.assertEqual(response.status_code, 503)
        with patch("app.core.auth.get_settings", return_value=Settings(api_token="weak")):
            response = self.client.get("/auth/check", headers={"Authorization": "Bearer weak"})
        self.assertEqual(response.status_code, 503)

    def test_cors_is_limited_to_configured_origins(self) -> None:
        for allowed_origin in (
            get_settings().cors_origins[0],
            "http://localhost:3100",
            "http://127.0.0.1:3100",
            "capacitor://localhost",
            "akashi://app",
        ):
            headers = {
                "Origin": allowed_origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            }
            allowed = self.client.options("/chat", headers=headers)
            self.assertEqual(allowed.status_code, 200)
            self.assertEqual(allowed.headers.get("access-control-allow-origin"), allowed_origin)

        headers = {
            "Origin": "capacitor://localhost",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        }
        denied = self.client.options("/chat", headers={**headers, "Origin": "https://unlisted.example"})
        self.assertNotIn("access-control-allow-origin", denied.headers)
