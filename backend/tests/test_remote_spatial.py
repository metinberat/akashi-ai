"""Spatial Lab as the first consumer of remote presence: authority, sync, leases, previews, provenance."""

import asyncio
import unittest

from app.devices.store import DeviceStore
from app.remote.runtime import RemoteRuntime
from app.remote.sessions import SessionConfig
from app.spatial.service import SpatialLabService
from tests.remote_support import Clock, Envelopes, drain, pair_and_open, temporary_root

run = asyncio.run
IDENTITY = {"position": [0, 0, 0], "rotation": [0, 0, 0, 1], "scale": 1}


class RemoteSpatialCase(unittest.TestCase):
    def setUp(self):
        self.root = temporary_root(self)
        self.clock = Clock()
        self.service = SpatialLabService(self.root / "spatial", form_data_dir=self.root / "no-form", interpreter="rules",
                                         monotonic=self.clock.monotonic)
        self.devices = DeviceStore(self.root / "devices.json", 600, 75)
        self.runtime = RemoteRuntime(self.devices, directory=self.root / "remote", spatial=self.service,
                                     config=SessionConfig(stale_after=12, idle_timeout=90), monotonic=self.clock.monotonic,
                                     wall_ms=self.clock.wall_ms)
        self.hub = self.runtime.hub
        self.spatial_id = self.service.create_session("Desk")["session"]["id"]
        added = self.service.submit_sync(self.spatial_id, {"type": "scene.add_asset", "fixture": "calibration"}, {"kind": "ui", "provider": "test"})
        self.object_id = added["targets"][0]
        self.phone = self.device("Metin's iPhone")
        self.mac = self.device("Mac", device_type="laptop")

    def device(self, name, device_type="phone", **kwargs):
        _, device_id, session, _ = run(pair_and_open(self.hub, name=name, device_type=device_type, **kwargs))
        envelopes = Envelopes(lambda: self.clock.wall_ms() - 25)
        client = {"session": session, "env": envelopes, "device_id": device_id}
        return client

    def send(self, client, kind, body=None, **kwargs):
        response = run(self.hub.receive(client["session"], client["env"].make(kind, body, **kwargs), "test"))
        return response

    def subscribe(self, client, **body):
        response = self.send(client, "spatial.subscribe", {"session_id": self.spatial_id, **body})
        self.assertEqual(response["kind"], "ack", response)
        return response["body"]

    def state(self):
        return self.service.session(self.spatial_id).history.state

    def revision(self):
        return self.service.session(self.spatial_id).history.revision


class AuthorityAndProvenanceTests(RemoteSpatialCase):
    def test_remote_command_goes_through_the_shared_path_with_device_provenance(self):
        sync = self.subscribe(self.phone)
        self.assertEqual(sync["mode"], "snapshot")
        response = self.send(self.phone, "spatial.command", {
            "request": {"type": "object.transform", "target": {"id": self.object_id}, "mode": "rotate", "degrees": 90},
            "base_revision": sync["revision"], "modality": "touch", "input": {"gesture": "two-finger twist"}})
        self.assertEqual(response["body"]["status"], "applied")
        event = self.service.session(self.spatial_id).history.events[-1]
        self.assertEqual(event["origin"]["kind"], "remote")
        remote = event["origin"]["remote"]
        self.assertEqual((remote["device_name"], remote["modality"], remote["session"]), ("Metin's iPhone", "touch", self.phone["session"].id))
        self.assertEqual(remote["seq"], response["seq"])
        self.assertTrue(self.service.session(self.spatial_id).history.verify_replay().verified)

    def test_why_did_this_move_names_the_remote_device(self):
        self.subscribe(self.phone)
        self.send(self.phone, "spatial.command", {"request": {"type": "object.transform", "target": {"id": self.object_id},
                                                              "mode": "translate", "delta": [0.3, 0, 0]}, "modality": "gesture"})
        record = self.service.provenance(self.spatial_id, self.object_id)
        self.assertIn("Remote hand gesture from Metin's iPhone", record["changes"][0]["origin"]["en"])
        outcome = run(self.service.interpret(self.spatial_id, "why did it move?"))
        self.assertEqual(outcome["query"], "provenance")
        self.assertIn("Metin's iPhone", outcome["reply"])
        turkish = run(self.service.interpret(self.spatial_id, "bunu kim taşıdı?"))
        self.assertIn("cihazından uzaktan el hareketi", turkish["reply"])
        self.assertEqual(self.revision(), 3)  # questions never change the scene

    def test_stale_absolute_command_never_moves_the_scene_backward(self):
        view = self.subscribe(self.phone)["revision"]
        self.subscribe(self.mac)
        moved = self.send(self.mac, "spatial.command", {"request": {"type": "object.transform", "target": {"id": self.object_id},
                                                                    "mode": "set", "transform": {**IDENTITY, "position": [1, 0, 0]}},
                                                        "base_revision": view, "modality": "pointer"})
        self.assertEqual(moved["body"]["status"], "applied")
        # The phone still believes the old revision and sends an absolute transform built from it.
        stale = self.send(self.phone, "spatial.command", {"request": {"type": "object.transform", "target": {"id": self.object_id},
                                                                      "mode": "set", "transform": {**IDENTITY, "position": [-1, 0, 0]}},
                                                          "base_revision": view, "modality": "touch"})
        self.assertEqual(stale["body"]["code"], "stale_state")
        self.assertIn("Mac", stale["body"]["details"]["changed_by"]["en"])
        self.assertEqual(self.state()["objects"][self.object_id]["transform"]["position"], [1.0, 0.0, 0.0])
        undo = self.send(self.phone, "spatial.command", {"request": {"type": "history.undo"}, "base_revision": view})
        self.assertEqual(undo["body"]["code"], "stale_state")  # undo from a stale view is refused too

    def test_selection_by_another_device_does_not_make_a_transform_stale(self):
        view = self.subscribe(self.phone)["revision"]
        self.subscribe(self.mac)
        self.send(self.mac, "spatial.command", {"request": {"type": "selection.select", "target": {"id": self.object_id}}})
        ok = self.send(self.phone, "spatial.command", {"request": {"type": "object.transform", "target": {"id": self.object_id},
                                                                   "mode": "scale", "factor": 1.5}, "base_revision": view})
        self.assertEqual(ok["body"]["status"], "applied")

    def test_duplicate_command_is_applied_once(self):
        self.subscribe(self.phone)
        message = self.phone["env"].make("spatial.command", {"request": {"type": "object.transform", "target": {"id": self.object_id},
                                                                         "mode": "translate", "delta": [0.1, 0, 0]}})
        before = self.revision()
        first = run(self.hub.receive(self.phone["session"], message, "test"))
        second = run(self.hub.receive(self.phone["session"], message, "test"))
        self.assertEqual(self.revision(), before + 1)
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["body"], second["body"])

    def test_viewer_scope_cannot_change_the_scene(self):
        viewer = self.device("Kiosk", scopes=("spatial.view",))
        self.subscribe(viewer)
        response = self.send(viewer, "spatial.command", {"request": {"type": "history.undo"}})
        self.assertEqual(response["body"]["code"], "forbidden")

    def test_http_callers_cannot_forge_remote_provenance(self):
        from app.spatial.service import RequestInvalid
        with self.assertRaises(RequestInvalid):
            self.service.submit_sync(self.spatial_id, {"type": "history.undo"}, {"kind": "remote", "provider": "x"})


class SyncTests(RemoteSpatialCase):
    def test_events_fan_out_in_order_with_patches_and_resubscribe_catches_up(self):
        first = self.subscribe(self.phone)
        drain(self.phone["session"])
        for dx in (0.1, 0.2, 0.3):
            self.service.submit_sync(self.spatial_id, {"type": "object.transform", "target": {"id": self.object_id}, "mode": "translate",
                                                       "delta": [dx, 0, 0]}, {"kind": "ui", "provider": "desk"})
            run(self.service._publish(self.spatial_id, {"events": self.service.session(self.spatial_id).history.events[-1:]}, {}))
        pushed = [m for m in drain(self.phone["session"]) if m["kind"] == "spatial.events"]
        seqs = [e["seq"] for m in pushed for e in m["body"]["events"]]
        self.assertEqual(seqs, list(range(first["revision"] + 1, self.revision() + 1)))
        self.assertTrue(all(e["patches"] for m in pushed for e in m["body"]["events"]))
        # A reconnecting client that holds revision R with the right digest gets only the missing events.
        resync = self.subscribe(self.phone, revision=first["revision"], digest=first["digest"])
        self.assertEqual(resync["mode"], "events")
        self.assertEqual(len(resync["events"]), 3)
        # A wrong digest (diverged copy, or Core restored another history) gets a full snapshot.
        diverged = self.subscribe(self.phone, revision=first["revision"], digest="sha256:" + "0" * 64)
        self.assertEqual(diverged["mode"], "snapshot")
        ahead = self.subscribe(self.phone, revision=self.revision() + 5, digest=first["digest"])
        self.assertEqual(ahead["mode"], "snapshot")

    def test_out_of_order_notifications_still_publish_in_history_order(self):
        self.subscribe(self.phone)
        drain(self.phone["session"])
        results = [self.service.submit_sync(self.spatial_id, {"type": "object.transform", "target": {"id": self.object_id},
                                                              "mode": "translate", "delta": [0.1, 0, 0]}, {"kind": "ui", "provider": "a"})
                   for _ in range(2)]
        run(self.service._publish(self.spatial_id, results[1], {}))  # the second finishes first
        run(self.service._publish(self.spatial_id, results[0], {}))
        seqs = [e["seq"] for m in drain(self.phone["session"]) if m["kind"] == "spatial.events" for e in m["body"]["events"]]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(seqs), len(set(seqs)))


class LeaseAndPreviewTests(RemoteSpatialCase):
    def begin(self, client):
        response = self.send(client, "spatial.lease.begin", {"object_id": self.object_id, "modality": "gesture",
                                                             "base_revision": self.revision()})
        self.assertEqual(response["kind"], "ack", response)
        return response["body"]["id"]

    def test_preview_streams_to_other_viewers_and_commit_is_one_history_entry(self):
        self.subscribe(self.phone)
        self.subscribe(self.mac)
        lease = self.begin(self.phone)
        drain(self.mac["session"])
        before = self.revision()
        for x in (0.1, 0.2, 0.3, 0.4):
            self.assertIsNone(self.send(self.phone, "spatial.preview", {"lease_id": lease, "transform": {**IDENTITY, "position": [x, 0, 0]}}))
        previews = [m for m in drain(self.mac["session"]) if m["kind"] == "spatial.preview"]
        self.assertEqual(len(previews), 1)  # coalesced: a slow viewer gets only the newest
        self.assertEqual(previews[0]["body"]["transform"]["position"], [0.4, 0, 0])
        self.assertEqual(previews[0]["body"]["holder"]["device_name"], "Metin's iPhone")
        self.assertEqual(self.revision(), before)  # previews are never history
        commit = self.send(self.phone, "spatial.command", {"request": {"type": "object.transform", "target": {"id": self.object_id},
                                                                       "mode": "set", "transform": {**IDENTITY, "position": [0.4, 0, 0]},
                                                                       "lease_id": lease}, "modality": "gesture",
                                                           "base_revision": before})
        self.assertEqual(commit["body"]["status"], "applied")
        self.assertEqual(self.revision(), before + 1)
        after_commit = drain(self.mac["session"])
        kinds = [m["kind"] if not m["body"].get("ended") else "preview.ended" for m in after_commit]
        self.assertEqual(kinds.count("preview.ended"), 1)
        # Viewers get the committed event before the preview ends: no snap back to the old transform.
        self.assertLess(kinds.index("spatial.events"), kinds.index("preview.ended"))

    def test_another_device_cannot_renew_preview_or_commit_a_lease_it_does_not_hold(self):
        self.subscribe(self.phone)
        self.subscribe(self.mac)
        lease = self.begin(self.phone)
        for kind, body in (("spatial.lease.end", {"lease_id": lease}),
                           ("spatial.command", {"request": {"type": "object.transform", "target": {"id": self.object_id}, "mode": "set",
                                                            "transform": {**IDENTITY, "position": [2, 0, 0]}, "lease_id": lease}})):
            self.assertEqual(self.send(self.mac, kind, body)["body"]["code"], "lease_not_yours")
        self.assertEqual(self.send(self.mac, "spatial.preview", {"lease_id": lease, "transform": IDENTITY})["body"]["code"], "lease_not_yours")
        self.assertEqual(self.send(self.mac, "spatial.lease.begin", {"object_id": self.object_id})["body"]["code"], "object_busy")

    def test_disconnect_releases_held_objects_to_the_committed_state(self):
        self.subscribe(self.phone)
        self.subscribe(self.mac)
        lease = self.begin(self.phone)
        self.send(self.phone, "spatial.preview", {"lease_id": lease, "transform": {**IDENTITY, "position": [3, 0, 0]}})
        drain(self.mac["session"])
        committed = self.state()["objects"][self.object_id]["transform"]
        self.clock.advance(4.5)  # the phone vanished: no renewals
        run(self.runtime.sweep())
        messages = drain(self.mac["session"])
        self.assertTrue(any(m["kind"] == "spatial.preview" and m["body"].get("ended") for m in messages))
        leases = [m for m in messages if m["kind"] == "spatial.leases"]
        self.assertEqual(leases[-1]["body"]["leases"], [])
        self.assertEqual(self.state()["objects"][self.object_id]["transform"], committed)
        # A new grab by another device now succeeds.
        self.assertEqual(self.send(self.mac, "spatial.lease.begin", {"object_id": self.object_id})["kind"], "ack")

    def test_revocation_releases_leases_immediately(self):
        self.subscribe(self.phone)
        self.begin(self.phone)
        self.devices.revoke(self.phone["device_id"])
        run(self.hub.revoke_device(self.phone["device_id"]))
        self.assertEqual(self.service.leases(self.spatial_id), [])

    def test_losing_control_scope_releases_leases(self):
        self.subscribe(self.phone)
        self.begin(self.phone)
        run(self.hub.set_grants(self.phone["device_id"], ["spatial.view"]))
        self.assertEqual(self.service.leases(self.spatial_id), [])
        self.assertEqual(self.send(self.phone, "spatial.lease.begin", {"object_id": self.object_id})["body"]["code"], "forbidden")

    def test_preview_outside_scene_limits_is_rejected(self):
        self.subscribe(self.phone)
        lease = self.begin(self.phone)
        bad = self.send(self.phone, "spatial.preview", {"lease_id": lease, "transform": {**IDENTITY, "position": [99, 0, 0]}})
        self.assertEqual(bad["body"]["code"], "bad_transform")


class PresenceTests(RemoteSpatialCase):
    def test_move_it_to_my_right_hand_uses_the_speaking_devices_hand(self):
        self.subscribe(self.phone)
        self.subscribe(self.mac)
        self.send(self.phone, "spatial.presence", {"anchors": {"right_hand": {"position": [1.2, 1.0, 0], "confidence": 0.9}},
                                                   "cursors": [{"hand": "right", "position": [1.2, 1.0, 0], "state": "open"}]})
        self.send(self.mac, "spatial.presence", {"anchors": {"right_hand": {"position": [-1.5, 0.5, 0], "confidence": 0.9}}})
        self.send(self.phone, "spatial.command", {"request": {"type": "selection.select", "target": {"id": self.object_id}}})
        reply = self.send(self.phone, "spatial.interpret", {"text": "move it to my right hand", "modality": "voice"})
        self.assertEqual(reply["body"]["applied"], 1, reply)
        self.assertEqual(self.state()["objects"][self.object_id]["transform"]["position"][0], 1.2)
        event = self.service.session(self.spatial_id).history.events[-1]
        self.assertEqual((event["origin"]["remote"]["modality"], event["origin"]["remote"]["device_name"]), ("voice", "Metin's iPhone"))
        roster = self.runtime.spatial.roster(self.spatial_id)
        phone_row = next(r for r in roster if r["session"] == self.phone["session"].id)
        self.assertEqual(phone_row["cursors"][0]["hand"], "right")

    def test_presence_needs_its_own_scope(self):
        viewer = self.device("Viewer", scopes=("spatial.view", "spatial.control"))
        self.subscribe(viewer)
        response = self.send(viewer, "spatial.presence", {"anchors": {}})
        self.assertEqual(response["body"]["code"], "forbidden")


class ConfirmationTests(RemoteSpatialCase):
    def test_requester_may_confirm_its_own_removal_other_devices_need_approval_scope(self):
        self.subscribe(self.phone)
        viewer = self.device("Watcher", scopes=("spatial.view", "spatial.control"))
        self.subscribe(viewer)
        pending = self.send(self.phone, "spatial.command", {"request": {"type": "scene.remove", "target": {"id": self.object_id}}})
        token = pending["body"]["token"]
        self.assertEqual(pending["body"]["status"], "confirmation_required")
        self.assertEqual(self.send(viewer, "spatial.confirm", {"token": token, "accept": True})["body"]["code"], "forbidden")
        done = self.send(self.phone, "spatial.confirm", {"token": token, "accept": True})
        self.assertEqual(done["body"]["status"], "applied")
        event = self.service.session(self.spatial_id).history.events[-1]
        self.assertEqual(event["origin"]["approval"]["by"], "requester")
        self.assertEqual(event["origin"]["approval"]["device_name"], "Metin's iPhone")
        self.assertNotIn(self.object_id, self.state()["objects"])


if __name__ == "__main__":
    unittest.main()
