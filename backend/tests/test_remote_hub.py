"""Remote presence foundation: pairing, key handshake, session lifecycle, message pipeline, audit."""

import asyncio
import json
import unittest

from app.devices.store import DeviceStore
from app.remote import identity, scopes
from app.remote.audit import AuditLog
from app.remote.hub import RemoteError, RemoteHub
from app.remote.sessions import Outbox, SessionAuthError, SessionConfig
from tests.remote_support import Clock, DeviceKey, Envelopes, drain, pair_and_open, temporary_root

run = asyncio.run


class HubCase(unittest.TestCase):
    def setUp(self):
        self.root = temporary_root(self)
        self.clock = Clock()
        self.devices = DeviceStore(self.root / "devices.json", 600, 75)
        self.audit = AuditLog(self.root / "audit")
        self.hub = RemoteHub(self.devices, audit=self.audit, config=SessionConfig(stale_after=12, idle_timeout=90, max_lifetime=3600),
                             monotonic=self.clock.monotonic, wall_ms=self.clock.wall_ms)
        self.applied = []

        async def apply(ctx):
            self.applied.append(ctx.envelope.body.get("value"))
            return {"count": len(self.applied)}

        async def realtime(ctx):
            self.applied.append(("rt", ctx.envelope.body.get("value")))
            return None

        self.hub.register("test.apply", apply, any_of=("spatial.control",))
        self.hub.register("test.view", apply, any_of=("spatial.view",))
        self.hub.register("test.general", apply, any_of=("approvals.general",))
        self.hub.register("test.live", realtime, delivery="realtime", any_of=("spatial.control",), max_age_ms=300)

    def open(self, **kwargs):
        return run(pair_and_open(self.hub, **kwargs))

    def kinds(self):
        return [event["kind"] for event in self.audit.recent(0, 500)["events"]]


class PairingAndHandshakeTests(HubCase):
    def test_key_handshake_opens_a_scoped_session_and_audits_it(self):
        key, device_id, session, welcome = self.open()
        self.assertEqual(welcome["kind"], "device")
        self.assertIn("spatial.control", welcome["scopes"])
        self.assertNotIn("approvals.general", welcome["scopes"])
        self.assertEqual(session.device["id"], device_id)
        stored = json.loads((self.root / "devices.json").read_text())
        record = next(d for d in stored["devices"] if d["id"] == device_id)
        self.assertEqual(record["role"], "presence")
        self.assertEqual(record["credential"], "key")
        self.assertNotIn("token_hash", record)
        self.assertEqual(record["capabilities"], [])  # never an agent-action target
        self.assertEqual(self.kinds()[:3], ["pairing.code_created", "device.paired", "session.opened"])
        self.assertNotIn(welcome["session_token"], (self.root / "devices.json").read_text())

    def test_presence_code_cannot_pair_an_agent_and_agent_actions_never_target_presence(self):
        code = self.hub.create_pairing_code(["spatial.view"], None)["code"]
        with self.assertRaises(PermissionError):
            self.devices.pair(code, "Agent", "desktop", ["take_screenshot"])  # agent path, presence code
        _, device_id, _, _ = self.open()
        with self.assertRaises(ValueError):
            self.devices.queue_action(device_id, "take_screenshot", {}, approved=True)

    def test_signature_nonce_and_scope_binding(self):
        key = DeviceKey()
        code = self.hub.create_pairing_code(scopes.PRESETS["spatial-remote"], None)["code"]
        device_id = self.hub.pair(code, "Phone", "phone", key.jwk())["device"]["id"]
        nonce = self.hub.challenge(device_id)["nonce"]
        wrong = DeviceKey()
        with self.assertRaises(RemoteError) as caught:
            run(self.hub.open_session(device_id, nonce=nonce, signature=wrong.proof(device_id, nonce)))
        self.assertEqual(caught.exception.code, "signature_invalid")
        # The nonce was consumed by the failed attempt: a captured proof cannot be replayed.
        with self.assertRaises(RemoteError) as caught:
            run(self.hub.open_session(device_id, nonce=nonce, signature=key.proof(device_id, nonce)))
        self.assertEqual(caught.exception.code, "nonce_invalid")
        # A proof for one scope set cannot open a session with other scopes.
        nonce = self.hub.challenge(device_id)["nonce"]
        with self.assertRaises(RemoteError) as caught:
            run(self.hub.open_session(device_id, nonce=nonce, signature=key.proof(device_id, nonce, ["spatial.view"]),
                                      requested=["spatial.view", "spatial.control"]))
        self.assertEqual(caught.exception.code, "signature_invalid")
        nonce = self.hub.challenge(device_id)["nonce"]
        welcome = run(self.hub.open_session(device_id, nonce=nonce, signature=key.proof(device_id, nonce, ["spatial.view"]),
                                            requested=["spatial.view"]))
        self.assertEqual(welcome["scopes"], ["spatial.view"])

    def test_nonce_expires_and_is_bound_to_its_device(self):
        _, device_a, _, _ = self.open(name="A")
        key_b = DeviceKey()
        code = self.hub.create_pairing_code(["spatial.view"], None)["code"]
        device_b = self.hub.pair(code, "B", "phone", key_b.jwk())["device"]["id"]
        nonce = self.hub.challenge(device_a)["nonce"]
        with self.assertRaises(RemoteError) as caught:
            run(self.hub.open_session(device_b, nonce=nonce, signature=key_b.proof(device_b, nonce)))
        self.assertEqual(caught.exception.code, "nonce_invalid")
        nonce = self.hub.challenge(device_b)["nonce"]
        self.clock.advance(61)
        with self.assertRaises(RemoteError):
            run(self.hub.open_session(device_b, nonce=nonce, signature=key_b.proof(device_b, nonce)))

    def test_private_or_off_curve_keys_are_refused_at_pairing(self):
        code = self.hub.create_pairing_code(["spatial.view"], None)["code"]
        jwk = DeviceKey().jwk()
        with self.assertRaises(RemoteError):
            self.hub.pair(code, "Phone", "phone", {**jwk, "d": "AAAA"})
        with self.assertRaises(RemoteError):
            self.hub.pair(code, "Phone", "phone", {**jwk, "y": jwk["x"]})
        with self.assertRaises(RemoteError):
            self.hub.pair(code, "Phone", "phone", {**jwk, "crv": "P-384"})

    def test_unknown_and_revoked_devices_are_rejected(self):
        with self.assertRaises(RemoteError) as caught:
            self.hub.challenge("no-such-device")
        self.assertEqual(caught.exception.code, "device_unknown")
        key, device_id, session, _ = self.open()
        self.devices.revoke(device_id)
        run(self.hub.revoke_device(device_id))
        self.assertEqual(session.state, "closed")
        self.assertEqual(session.close_reason, "revoked")
        with self.assertRaises(RemoteError):
            self.hub.challenge(device_id)

    def test_secret_credential_fallback_is_weaker_but_works(self):
        code = self.hub.create_pairing_code(["spatial.view"], None)["code"]
        paired = self.hub.pair(code, "Old browser", "laptop", None)
        self.assertIn("device_secret", paired)
        self.assertEqual(paired["device"]["credential"], "secret")
        device_id = paired["device"]["id"]
        with self.assertRaises(RemoteError):
            run(self.hub.open_session(device_id, secret="wrong-secret"))
        welcome = run(self.hub.open_session(device_id, secret=paired["device_secret"]))
        self.assertEqual(welcome["scopes"], ["spatial.view"])

    def test_handshakes_are_rate_limited_per_device(self):
        _, device_id, _, _ = self.open()
        with self.assertRaises(RemoteError) as caught:
            for _ in range(20):
                self.hub.challenge(device_id)
        self.assertEqual(caught.exception.code, "rate_limited")

    def test_session_token_authenticates_only_its_session(self):
        _, _, session, welcome = self.open()
        self.assertIs(self.hub.authenticate(session.id, welcome["session_token"]), session)
        with self.assertRaises(SessionAuthError):
            self.hub.authenticate(session.id, "x" + welcome["session_token"])
        with self.assertRaises(SessionAuthError):
            self.hub.authenticate(session.id, None, owner_token_valid=True)  # API token only for owner sessions
        owner = run(self.hub.open_owner_session("Desk"))
        self.assertTrue(self.hub.authenticate(owner["session_id"], None, owner_token_valid=True))


class PipelineTests(HubCase):
    def setUp(self):
        super().setUp()
        self.key, self.device_id, self.session, _ = self.open()
        self.env = Envelopes(lambda: self.clock.wall_ms() - 40)  # a device clock 40 ms behind + no delay

    def send(self, message):
        return run(self.hub.receive(self.session, message, "test"))

    def test_duplicate_message_is_answered_from_cache_and_never_reapplied(self):
        message = self.env.make("test.apply", {"value": 1})
        first = self.send(message)
        again = self.send(message)
        self.assertEqual(self.applied, [1])
        self.assertEqual(first["kind"], "ack")
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["body"], first["body"])

    def test_out_of_order_reliable_message_is_rejected_not_applied(self):
        late = self.env.make("test.apply", {"value": "old"})
        newer = self.env.make("test.apply", {"value": "new"})
        self.send(newer)
        response = self.send(late)
        self.assertEqual(response["body"]["code"], "out_of_order")
        self.assertEqual(self.applied, ["new"])

    def test_realtime_input_is_latest_wins_and_stale_input_is_dropped(self):
        a, b = self.env.make("test.live", {"value": "a"}), self.env.make("test.live", {"value": "b"})
        self.send(b)
        self.assertIsNone(self.send(a))  # superseded
        self.assertEqual(self.applied, [("rt", "b")])
        # A burst released after a stall: sent 2 s ago relative to the learned offset.
        stale = self.env.make("test.live", {"value": "stale"}, t=self.clock.wall_ms() - 40 - 2000)
        self.assertIsNone(self.send(stale))
        self.assertEqual(self.applied, [("rt", "b")])
        self.assertEqual(self.session.stats["stale_input"], 1)

    def test_constant_clock_skew_does_not_make_input_stale(self):
        skewed = Envelopes(lambda: self.clock.wall_ms() + 7_200_000)  # device clock two hours ahead
        for value in range(5):
            self.send(skewed.make("test.live", {"value": value}))
        self.assertEqual(len(self.applied), 5)

    def test_scope_is_enforced_and_refusals_are_audited(self):
        response = self.send(self.env.make("test.general", {"value": 1}))
        self.assertEqual(response["body"]["code"], "forbidden")
        self.assertEqual(self.applied, [])
        self.assertIn("message.forbidden", self.kinds())

    def test_unknown_kind_and_malformed_envelopes(self):
        self.assertEqual(self.send(self.env.make("test.nope"))["body"]["code"], "unknown_kind")
        self.assertEqual(self.send("{not json")["body"]["code"], "bad_envelope")
        self.assertEqual(self.send({"v": 2, "id": "abcdefgh", "seq": 1, "t": 1, "kind": "ping"})["body"]["code"], "bad_version")
        self.assertEqual(self.send("x" * 70_000)["body"]["code"], "too_large")

    def test_rate_limit_rejects_without_consuming_the_message(self):
        responses = [self.send(self.env.make("test.apply", {"value": i})) for i in range(60)]
        limited = [r for r in responses if r["kind"] == "error"]
        self.assertTrue(limited and all(r["body"]["code"] == "rate_limited" and r["body"]["retryable"] for r in limited))
        self.clock.advance(5)
        retried = self.send({**self.env.make("test.apply", {"value": "retry"})})
        self.assertEqual(retried["kind"], "ack")

    def test_revocation_and_grant_changes_apply_to_live_sessions_immediately(self):
        self.assertEqual(self.send(self.env.make("test.apply", {"value": 1}))["kind"], "ack")
        run(self.hub.set_grants(self.device_id, ["spatial.view"]))
        self.assertEqual(self.session.scopes, frozenset({"spatial.view"}))
        self.assertEqual(self.send(self.env.make("test.apply", {"value": 2}))["body"]["code"], "forbidden")
        self.assertIn("session.updated", [m["kind"] for m in drain(self.session)])
        self.devices.revoke(self.device_id)  # the owner revokes through the device registry
        response = self.send(self.env.make("test.view", {"value": 3}))
        self.assertEqual(response["body"]["code"], "session_revoked")
        self.assertEqual(self.applied, [1])

    def test_lifecycle_stale_then_closed_and_closed_never_reopens(self):
        events = []
        self.hub.on("stale", lambda s: events.append(("stale", s.id)))
        self.hub.on("closed", lambda s: events.append(("closed", s.id)))
        self.clock.advance(13)
        run(self.hub.sweep())
        self.assertEqual(self.session.state, "stale")
        self.send(self.env.make("ping"))
        self.assertEqual(self.session.state, "open")
        self.clock.advance(91)
        run(self.hub.sweep())
        self.assertEqual(self.session.state, "closed")
        self.assertEqual(events, [("stale", self.session.id), ("closed", self.session.id)])
        self.assertEqual(self.send(self.env.make("test.view"))["body"]["code"], "session_expired")

    def test_ping_measures_age_and_acks_the_outbox(self):
        self.session.outbox.push("x", {})
        response = self.send(self.env.make("ping", {"ack": self.session.outbox.sseq}))
        self.assertEqual(response["kind"], "ack")
        self.assertIn("server_ms", response["body"])
        self.assertEqual(self.session.outbox.acked, self.session.outbox.sseq)


class OutboxTests(unittest.TestCase):
    def test_coalescing_keeps_only_the_newest_lossy_message_without_spurious_resync(self):
        box = Outbox()
        box.push("event", {"n": 1})
        for i in range(5):
            box.push("preview", {"n": i}, coalesce="lease-1")
        messages, covered = box.after(0)
        self.assertTrue(covered)
        self.assertEqual([m["kind"] for m in messages], ["event", "preview"])
        self.assertEqual(messages[-1]["body"], {"n": 4})

    def test_resume_window_and_backlog_overflow(self):
        box = Outbox()
        for i in range(600):
            box.push("event", {"n": i})
        messages, covered = box.after(0)
        self.assertEqual(messages[0]["kind"], "resync_required")  # overflow dropped the backlog
        self.assertFalse(covered)
        box = Outbox()
        for i in range(400):
            box.push("event", {"n": i})
            box.ack(box.sseq)
        self.assertFalse(box.after(10)[1])  # trimmed out of the retained window
        self.assertTrue(box.after(box.sseq - 5)[1])


class AuditTests(unittest.TestCase):
    def test_tampered_audit_log_fails_closed(self):
        root = temporary_root(self)
        audit = AuditLog(root / "audit")
        audit.record("x", detail=1)
        audit.record("y", detail=2)
        self.assertTrue(audit.verify()["verified"])
        segment = next((root / "audit").iterdir())
        path = segment / "events.jsonl"
        path.write_text(path.read_text().replace('"detail":1', '"detail":9'))
        self.assertFalse(audit.verify()["verified"])
        reopened = AuditLog(root / "audit")
        self.assertIsNotNone(reopened.broken)
        hub = RemoteHub(DeviceStore(root / "devices.json", 600, 75), audit=reopened)
        with self.assertRaises(Exception):
            hub.create_pairing_code(["spatial.view"])


class ScopeTests(unittest.TestCase):
    def test_prerequisites_and_effective_scopes(self):
        self.assertEqual(scopes.normalize(["voice.spatial"]), frozenset({"voice.spatial", "spatial.view", "spatial.control"}))
        self.assertEqual(scopes.effective(["spatial.control", "approvals.general"], ["spatial.view", "spatial.control"]),
                         frozenset({"spatial.view", "spatial.control"}))
        self.assertEqual(scopes.effective(None, ["spatial.control"]), frozenset())  # control without view is unusable
        with self.assertRaises(scopes.ScopeError):
            scopes.normalize(["computer.control"])
        self.assertFalse(any(s.startswith(("computer", "agent", "files", "browser")) for s in scopes.SCOPES))


class IdentityTests(unittest.TestCase):
    def test_proof_message_is_canonical(self):
        self.assertEqual(identity.proof_message("dev", "n", ["b", "a", "a"]), b"akashi.remote.session/1\ndev\nn\na,b")
        self.assertEqual(identity.proof_message("dev", "n", None), b"akashi.remote.session/1\ndev\nn\n*")
        key = DeviceKey()
        jwk = identity.normalize_public_jwk(key.jwk())
        message = identity.proof_message("dev", "n", None)
        self.assertTrue(identity.verify(jwk, message, key.sign(message)))
        self.assertFalse(identity.verify(jwk, message + b"x", key.sign(message)))
        self.assertFalse(identity.verify(jwk, message, "not-a-signature"))


if __name__ == "__main__":
    unittest.main()
