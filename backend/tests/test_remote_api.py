"""Remote presence through AKASHI's real HTTP and WebSocket surface."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.absolute import AkashiCore, get_core
from app.main import app
from tests.remote_support import API_TOKEN, DeviceKey, Envelopes, settings_for, temporary_root


class RemoteApiTests(unittest.TestCase):
    def setUp(self):
        self.root = temporary_root(self)
        self.settings = settings_for(self.root, spatial_interpreter="rules")
        self.core = AkashiCore(self.settings)
        app.dependency_overrides[get_core] = lambda: self.core
        self.addCleanup(app.dependency_overrides.clear)
        for target in ("app.core.auth.get_settings", "app.api.remote.get_settings"):
            patcher = patch(target, return_value=self.settings)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(app)
        self.owner = {"Authorization": f"Bearer {API_TOKEN}"}
        created = self.client.post("/spatial/sessions", headers=self.owner, json={"label": "Desk"}).json()
        self.spatial_id = created["session"]["id"]
        added = self.client.post(f"/spatial/sessions/{self.spatial_id}/commands", headers=self.owner,
                                 json={"request": {"type": "scene.add_asset", "fixture": "calibration"}}).json()
        self.object_id = added["result"]["targets"][0] if "result" in added else added["targets"][0]

    def pair(self, name="iPhone", preset="spatial-remote", scopes=None):
        body = {"label": name, **({"scopes": scopes} if scopes is not None else {"preset": preset})}
        code = self.client.post("/remote/pairing-codes", headers=self.owner, json=body)
        self.assertEqual(code.status_code, 201, code.text)
        key = DeviceKey()
        paired = self.client.post("/remote/pair", json={"code": code.json()["code"], "name": name, "device_type": "phone",
                                                        "public_key": key.jwk()})
        self.assertEqual(paired.status_code, 201, paired.text)
        self.assertNotIn("device_secret", paired.json())
        return key, paired.json()["device"]["id"]

    def open(self, key, device_id, scopes=None):
        nonce = self.client.post("/remote/challenge", json={"device_id": device_id}).json()["nonce"]
        response = self.client.post("/remote/sessions", json={"device_id": device_id, "nonce": nonce,
                                                               "signature": key.proof(device_id, nonce, scopes), "scopes": scopes,
                                                               "capabilities": ["touch", "display", "camera"], "client": {"app": "test"}})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_owner_endpoints_require_the_api_token(self):
        for method, path in (("post", "/remote/pairing-codes"), ("get", "/remote/devices"), ("get", "/remote/approvals"),
                             ("get", "/remote/audit"), ("post", "/remote/owner-sessions"), ("get", "/remote/status")):
            self.assertEqual(getattr(self.client, method)(path).status_code, 401, path)

    def test_handshake_rejections(self):
        key, device_id = self.pair()
        nonce = self.client.post("/remote/challenge", json={"device_id": device_id}).json()["nonce"]
        bad = self.client.post("/remote/sessions", json={"device_id": device_id, "nonce": nonce, "signature": DeviceKey().proof(device_id, nonce)})
        self.assertEqual((bad.status_code, bad.json()["code"]), (401, "signature_invalid"))
        unknown = self.client.post("/remote/challenge", json={"device_id": "00000000-0000-0000-0000-000000000000"})
        self.assertEqual((unknown.status_code, unknown.json()["code"]), (401, "device_unknown"))
        used = self.client.post("/remote/pair", json={"code": "ABCDEFGHIJ", "name": "x", "public_key": key.jwk()})
        self.assertEqual((used.status_code, used.json()["code"]), (401, "pairing_refused"))

    def test_http_transport_commands_and_long_poll(self):
        key, device_id = self.pair()
        session = self.open(key, device_id)
        auth = {"Authorization": f"Bearer {session['session_token']}"}
        env = Envelopes()
        sub = self.client.post(f"/remote/sessions/{session['session_id']}/messages", headers=auth,
                               json={"messages": [env.make("spatial.subscribe", {"session_id": self.spatial_id})]}).json()
        self.assertEqual(sub["responses"][0]["kind"], "ack")
        revision = sub["responses"][0]["body"]["revision"]
        cursor = sub["sseq"]
        command = env.make("spatial.command", {"request": {"type": "object.transform", "target": {"id": self.object_id},
                                                           "mode": "rotate", "degrees": 45}, "base_revision": revision, "modality": "touch"})
        result = self.client.post(f"/remote/sessions/{session['session_id']}/messages", headers=auth,
                                  json={"messages": [command, command]}).json()["responses"]
        self.assertEqual(result[0]["body"]["status"], "applied")
        self.assertTrue(result[1]["duplicate"])
        polled = self.client.get(f"/remote/sessions/{session['session_id']}/poll", headers=auth, params={"after": cursor, "wait": 0}).json()
        events = [e for m in polled["messages"] if m["kind"] == "spatial.events" for e in m["body"]["events"]]
        self.assertEqual([e["seq"] for e in events], [revision + 1])
        self.assertEqual(events[0]["origin"]["device"]["name"], "iPhone")
        self.assertFalse(polled["resync"])
        wrong = self.client.get(f"/remote/sessions/{session['session_id']}/poll", headers={"Authorization": "Bearer nope"})
        self.assertEqual(wrong.status_code, 401)
        # Device-scoped asset access with the session token, never the API token.
        asset_id = self.core.spatial.session(self.spatial_id).history.state["objects"][self.object_id]["asset"]["asset_id"]
        content = self.client.get(f"/remote/sessions/{session['session_id']}/assets/{asset_id}", headers=auth)
        self.assertEqual((content.status_code, content.headers["content-type"]), (200, "model/gltf-binary"))

    def test_websocket_auth_resume_push_and_revocation(self):
        key, device_id = self.pair()
        session = self.open(key, device_id)
        other_key, other_id = self.pair("Mac")
        other = self.open(other_key, other_id)
        with self.client.websocket_connect("/remote/ws") as ws:
            ws.send_json({"type": "auth", "session_id": session["session_id"], "token": session["session_token"]})
            welcome = ws.receive_json()
            self.assertEqual(welcome["kind"], "session.welcome")
            env = Envelopes()
            ws.send_json(env.make("spatial.subscribe", {"session_id": self.spatial_id}))
            ack = None
            while ack is None:
                message = ws.receive_json()
                ack = message if message.get("kind") == "ack" else None
            # The Mac changes the scene over HTTP; the phone's socket receives the event.
            mac_env = Envelopes()
            auth = {"Authorization": f"Bearer {other['session_token']}"}
            self.client.post(f"/remote/sessions/{other['session_id']}/messages", headers=auth,
                             json={"messages": [mac_env.make("spatial.subscribe", {"session_id": self.spatial_id}),
                                                mac_env.make("spatial.command", {"request": {"type": "object.visibility", "target": {"id": self.object_id},
                                                                                             "visible": False}})]})
            pushed = None
            for _ in range(20):
                message = ws.receive_json()
                if message.get("kind") == "spatial.events":
                    pushed = message
                    break
            self.assertIsNotNone(pushed)
            self.assertIn("Mac", pushed["body"]["events"][-1]["origin"]["en"])
            # The owner revokes the phone: the live socket is told and closed immediately.
            revoked = self.client.delete(f"/remote/devices/{device_id}", headers=self.owner)
            self.assertEqual(revoked.json()["sessions_closed"], 1)
            kinds = []
            with self.assertRaises(WebSocketDisconnect) as closed:
                for _ in range(20):
                    kinds.append(ws.receive_json()["kind"])
            self.assertIn("revoked", kinds)
            self.assertEqual(closed.exception.code, 4403)
        # The revoked device can neither use its token nor start a new handshake.
        dead = self.client.post(f"/remote/sessions/{session['session_id']}/messages",
                                headers={"Authorization": f"Bearer {session['session_token']}"}, json={"messages": []})
        self.assertEqual(dead.json()["code"], "session_revoked")
        self.assertEqual(self.client.post("/remote/challenge", json={"device_id": device_id}).status_code, 401)

    def test_websocket_rejects_bad_credentials_and_foreign_origins(self):
        with self.client.websocket_connect("/remote/ws") as ws:
            ws.send_json({"type": "auth", "session_id": "rs-0000000000000000", "token": "nope"})
            self.assertEqual(ws.receive_json()["body"]["code"], "session_unknown")
            with self.assertRaises(WebSocketDisconnect) as closed:
                ws.receive_json()
            self.assertEqual(closed.exception.code, 4401)
        with self.assertRaises(WebSocketDisconnect) as refused:
            with self.client.websocket_connect("/remote/ws", headers={"Origin": "https://evil.example"}) as ws:
                ws.receive_json()
        self.assertEqual(refused.exception.code, 4403)

    def test_owner_session_uses_the_api_token_through_the_http_transport(self):
        opened = self.client.post("/remote/owner-sessions", headers=self.owner, json={"label": "Desktop"})
        self.assertEqual(opened.status_code, 201)
        session_id = opened.json()["session_id"]
        env = Envelopes()
        response = self.client.post(f"/remote/sessions/{session_id}/messages", headers=self.owner,
                                    json={"messages": [env.make("devices.providers", {"capability": "camera"})]}).json()
        self.assertEqual(response["responses"][0]["kind"], "ack")
        key, device_id = self.pair()
        device = self.open(key, device_id)
        # The API token never authenticates a device session, and a device cannot use owner-only kinds.
        self.assertEqual(self.client.post(f"/remote/sessions/{device['session_id']}/messages", headers=self.owner,
                                          json={"messages": []}).status_code, 401)
        forbidden = self.client.post(f"/remote/sessions/{device['session_id']}/messages",
                                     headers={"Authorization": f"Bearer {device['session_token']}"},
                                     json={"messages": [Envelopes().make("devices.providers")]}).json()
        self.assertEqual(forbidden["responses"][0]["body"]["code"], "forbidden")

    def test_grants_change_and_devices_listing(self):
        key, device_id = self.pair()
        session = self.open(key, device_id)
        listed = self.client.get("/remote/devices", headers=self.owner).json()["devices"]
        self.assertEqual(listed[0]["sessions"][0]["id"], session["session_id"])
        self.assertNotIn("public_key", listed[0])
        changed = self.client.patch(f"/remote/devices/{device_id}", headers=self.owner, json={"scopes": ["spatial.view"]})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(self.core.remote.hub.sessions.get(session["session_id"]).scopes, frozenset({"spatial.view"}))
        bad = self.client.patch(f"/remote/devices/{device_id}", headers=self.owner, json={"scopes": ["computer.control"]})
        self.assertEqual(bad.json()["code"], "bad_scopes")
        providers = self.client.get("/remote/providers", headers=self.owner, params={"capability": "camera"}).json()
        self.assertEqual(providers["providers"][0]["device"]["name"], "iPhone")

    def test_owner_decides_approvals_and_audit_verifies(self):
        self.client.post(f"/spatial/sessions/{self.spatial_id}/commands", headers=self.owner,
                         json={"request": {"type": "scene.remove", "target": {"id": self.object_id}}})
        pending = self.client.get("/remote/approvals", headers=self.owner).json()["approvals"]
        self.assertEqual(len(pending), 1)
        decided = self.client.post(f"/remote/approvals/{pending[0]['id']}", headers=self.owner, json={"approve": False})
        self.assertEqual(decided.json()["decision"], "deny")
        self.assertIn(self.object_id, self.core.spatial.session(self.spatial_id).history.state["objects"])
        audit = self.client.get("/remote/audit", headers=self.owner).json()
        self.assertEqual(audit["events"][-1]["kind"], "approval.decided")
        self.assertTrue(self.client.post("/remote/audit/verify", headers=self.owner).json()["verified"])

    def test_callers_cannot_claim_remote_provenance_and_presence_devices_cannot_act_as_agents(self):
        forged = self.client.post(f"/spatial/sessions/{self.spatial_id}/commands", headers=self.owner,
                                  json={"request": {"type": "history.undo"}, "origin": {"kind": "remote", "provider": "x"}})
        self.assertEqual(forged.json()["code"], "origin_reserved")
        code = self.client.post("/remote/pairing-codes", headers=self.owner, json={"preset": "spatial-viewer"}).json()["code"]
        paired = self.client.post("/remote/pair", json={"code": code, "name": "Old", "device_type": "laptop"}).json()
        secret, device_id = paired["device_secret"], paired["device"]["id"]
        agent = self.client.get("/devices/agent/actions", headers={"Authorization": f"Bearer {secret}", "X-Akashi-Device-Id": device_id})
        self.assertEqual(agent.status_code, 401)
        # The legacy device route revokes presence devices too, closing their sessions.
        session = self.client.post("/remote/sessions", json={"device_id": device_id, "secret": secret}).json()
        self.assertEqual(self.client.delete(f"/devices/{device_id}", headers=self.owner).status_code, 200)
        self.assertEqual(self.core.remote.hub.sessions.get(session["session_id"]).close_reason, "revoked")


if __name__ == "__main__":
    unittest.main()
