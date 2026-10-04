"""Remote approvals, remote voice and capability awareness against a real AkashiCore."""

import asyncio
import unittest
from unittest.mock import patch

from app.core.absolute import AkashiCore
from app.remote import context as remote_context
from tests.remote_support import Envelopes, pair_and_open, settings_for, temporary_root


class RemoteCoreCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.root = temporary_root(self)
        self.settings = settings_for(self.root, spatial_interpreter="rules")
        patcher = patch("app.core.auth.get_settings", return_value=self.settings)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.core = AkashiCore(self.settings)
        self.hub = self.core.remote.hub
        self.spatial_id = self.core.spatial.create_session("Desk")["session"]["id"]
        added = self.core.spatial.submit_sync(self.spatial_id, {"type": "scene.add_asset", "fixture": "calibration"},
                                              {"kind": "ui", "provider": "desk"})
        self.object_id = added["targets"][0]

    async def device(self, name, scopes, capabilities=("touch", "display")):
        _, device_id, session, _ = await pair_and_open(self.hub, name=name, scopes=scopes, capabilities=capabilities)
        return {"session": session, "env": Envelopes(), "device_id": device_id}

    async def send(self, client, kind, body=None):
        return await self.hub.receive(client["session"], client["env"].make(kind, body), "test")

    async def subscribe(self, client):
        response = await self.send(client, "spatial.subscribe", {"session_id": self.spatial_id})
        self.assertEqual(response["kind"], "ack", response)


class ApprovalTests(RemoteCoreCase):
    async def test_phone_approves_a_desktop_removal_with_audited_device_origin(self):
        pending = self.core.spatial.submit_sync(self.spatial_id, {"type": "scene.remove", "target": {"id": self.object_id}},
                                                {"kind": "language", "provider": "desktop-voice"})
        self.assertEqual(pending["status"], "confirmation_required")
        phone = await self.device("Metin's iPhone", ("spatial.view", "approvals.spatial"))
        listed = await self.send(phone, "approvals.list")
        items = listed["body"]["approvals"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["scope"], "spatial")
        self.assertIn("Remove", items[0]["title"])
        self.assertIn("removing", items[0]["reason"].lower())
        decided = await self.send(phone, "approval.decide", {"approval_id": items[0]["id"], "approve": True})
        self.assertEqual(decided["body"]["status"], "decided")
        self.assertNotIn(self.object_id, self.core.spatial.session(self.spatial_id).history.state["objects"])
        event = self.core.spatial.session(self.spatial_id).history.events[-1]
        self.assertEqual(event["origin"]["approval"]["device_name"], "Metin's iPhone")
        self.assertEqual(event["origin"]["kind"], "language")  # the request's own origin is preserved
        audit = [e for e in self.core.remote.audit.recent(0, 500)["events"] if e["kind"] == "approval.decided"]
        self.assertEqual(audit[-1]["by"]["device_name"], "Metin's iPhone")
        self.assertEqual(audit[-1]["by"]["session"], phone["session"].id)
        again = await self.send(phone, "approval.decide", {"approval_id": items[0]["id"], "approve": True})
        self.assertEqual(again["body"]["status"], "already_decided")
        self.assertTrue(self.core.remote.audit.verify()["verified"])

    async def test_spatial_approver_cannot_see_or_decide_general_task_approvals(self):
        task = await self.core.tasks.create("Confirm a removal", [{"tool": "spatial.confirm", "arguments": {
            "session_id": self.spatial_id, "token": "nope"}}])
        for _ in range(50):
            if (self.core.tasks.store.get(task["id"]) or {}).get("status") == "waiting_for_approval":
                break
            await asyncio.sleep(0.01)
        self.assertEqual(self.core.tasks.store.get(task["id"])["status"], "waiting_for_approval")
        spatial_only = await self.device("Phone", ("spatial.view", "approvals.spatial"))
        listed = await self.send(spatial_only, "approvals.list")
        self.assertEqual(listed["body"]["approvals"], [])
        refused = await self.send(spatial_only, "approval.decide", {"approval_id": f"task:{task['id']}", "approve": True})
        self.assertEqual(refused["body"]["code"], "forbidden")
        self.assertEqual(self.core.tasks.store.get(task["id"])["status"], "waiting_for_approval")
        approver = await self.device("Mac", ("approvals.general",))
        listed = await self.send(approver, "approvals.list")
        self.assertEqual([item["id"] for item in listed["body"]["approvals"]], [f"task:{task['id']}"])
        self.assertIn("spatial.confirm", listed["body"]["approvals"][0]["reason"])
        denied = await self.send(approver, "approval.decide", {"approval_id": f"task:{task['id']}", "approve": False})
        self.assertEqual(denied["body"]["decision"], "deny")
        self.assertEqual(self.core.tasks.store.get(task["id"])["status"], "cancelled")

    async def test_approval_changes_are_pushed_to_approver_sessions(self):
        phone = await self.device("Phone", ("spatial.view", "approvals.spatial"))
        phone["session"].outbox.ack(phone["session"].outbox.sseq)
        self.core.spatial.submit_sync(self.spatial_id, {"type": "scene.remove", "target": {"id": self.object_id}},
                                      {"kind": "ui", "provider": "desk"})
        await self.core.remote.sweep()
        pushed = [m for m in phone["session"].outbox.after(phone["session"].outbox.acked)[0] if m["kind"] == "approvals.changed"]
        self.assertEqual(len(pushed[-1]["body"]["approvals"]), 1)


class VoiceTests(RemoteCoreCase):
    async def test_remote_voice_runs_through_the_spatial_command_path(self):
        phone = await self.device("Phone", ("spatial.view", "spatial.control", "voice.spatial"), ("microphone", "voice_input"))
        await self.subscribe(phone)
        await self.send(phone, "spatial.command", {"request": {"type": "selection.select", "target": {"id": self.object_id}}})
        response = await self.send(phone, "voice.utterance", {"text": "rotate it 90 degrees", "language": "en", "engine": "ios-native"})
        body = response["body"]
        self.assertEqual((body["route"], body["understood"]), ("spatial", True), body)
        event = self.core.spatial.session(self.spatial_id).history.events[-1]
        self.assertEqual(event["origin"]["remote"]["modality"], "voice")
        self.assertTrue(event["origin"]["input"]["voice"])
        voice = self.core.voice_sessions.get(body["voice_session"])
        self.assertEqual(voice["state"], "speaking")

    async def test_scene_only_device_never_reaches_the_general_assistant(self):
        phone = await self.device("Phone", ("spatial.view", "spatial.control", "voice.spatial"))
        await self.subscribe(phone)
        called = []

        async def chat(**kwargs):
            called.append(kwargs)
        self.core.remote.voice.chat = chat
        response = await self.send(phone, "voice.utterance", {"text": "open VS Code and take a screenshot", "language": "en"})
        self.assertEqual(response["body"]["route"], "none")
        self.assertIn("only give scene instructions", response["body"]["reply"])
        self.assertEqual(called, [])

    async def test_assistant_chat_scope_keeps_live_actions_scene_bounded(self):
        approver = await self.device("Mac", ("spatial.view", "spatial.control", "voice.spatial", "assistant.chat"))
        await self.subscribe(approver)
        selected = []
        original = self.core.live.registry.select

        def spy(message):
            result = original(message)
            selected.append((message, result[0].definition.name if result else None, remote_context.current() is not None))
            return result
        self.core.live.registry.select = spy  # type: ignore[assignment]
        response = await self.send(approver, "voice.utterance", {"text": "VS Code'u aç.", "language": "tr"})
        self.assertEqual(response["body"]["route"], "assistant")
        self.assertEqual(selected, [("VS Code'u aç.", None, True)])  # application.open was not reachable

    async def test_voice_needs_a_voice_scope(self):
        viewer = await self.device("Viewer", ("spatial.view",))
        response = await self.send(viewer, "voice.utterance", {"text": "hide it"})
        self.assertEqual(response["body"]["code"], "forbidden")


class CapabilityTests(RemoteCoreCase):
    async def test_which_device_can_provide_a_camera(self):
        await self.device("Metin's iPhone", ("spatial.view",), ({"name": "camera", "state": "available", "detail": {"facing": "user"}},
                                                               "microphone", "touch"))
        await self.device("Mac", ("spatial.view",), ("display", "keyboard", "pointer"))
        providers = self.hub.registry.providers("camera")
        self.assertEqual([p.device["name"] for p in providers], ["Metin's iPhone"])
        reply = await self.core.chat("Which device can provide a camera?", "s", "private")
        self.assertIn("Metin's iPhone", reply.text)
        self.assertEqual(reply.provider, "remote-presence")
        turkish = await self.core.chat("Hangi cihazlar bağlı?", "s", "private")
        self.assertIn("Mac", turkish.text)
        tool = await self.core.tools.invoke("remote.devices", {"capability": "keyboard"})
        self.assertEqual([p["device"]["name"] for p in tool["data"]["providers"]], ["Mac"])

    async def test_capabilities_change_during_a_session(self):
        phone = await self.device("Phone", ("spatial.view",), ("camera",))
        response = await self.send(phone, "capabilities.update", {"capabilities": [{"name": "camera", "state": "denied"}]})
        self.assertEqual(response["kind"], "ack")
        self.assertEqual(self.hub.registry.providers("camera"), [])
        bad = await self.send(phone, "capabilities.update", {"capabilities": ["teleporter"]})
        self.assertEqual(bad["body"]["code"], "bad_capabilities")


if __name__ == "__main__":
    unittest.main()
