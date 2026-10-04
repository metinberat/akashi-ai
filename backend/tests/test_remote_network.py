"""Deterministic network-fault simulation of several remote devices against one authoritative Core.

Every run is seeded: the same seed produces the same latencies, losses,
duplicates and reorderings. Each virtual device implements the client side of
``akashi.remote/1`` the way the real clients do: reliable messages are retried
with the same id/seq until answered, the downlink is pulled after a cursor (the
HTTP transport's semantics), scene state is applied event by event by revision,
and any gap, digest mismatch or lost session triggers a re-sync or a new
handshake with the device key.

These are cloud simulations of network behaviour, not measurements of a real
Wi-Fi network (see docs/acceptance/remote-spatial-presence-v1-5.md).
"""

import asyncio
import copy
import heapq
import itertools
import random
import unittest
from typing import Any, Callable, Dict, List, Optional

from app.devices.store import DeviceStore
from app.history import patch as patches
from app.history.canonical import digest
from app.remote import protocol, scopes
from app.remote.runtime import RemoteRuntime
from app.remote.sessions import SessionAuthError, SessionConfig
from app.spatial.service import SpatialLabService
from tests.remote_support import Clock, DeviceKey, temporary_root

IDENTITY = {"position": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0, 1.0], "scale": 1.0}


class Network:
    """Seeded datagram network: random latency (hence reordering), loss and duplication."""

    def __init__(self, rng: random.Random, clock: Clock, *, loss=0.0, duplicate=0.0, latency=(0.004, 0.120)) -> None:
        self.rng, self.clock = rng, clock
        self.loss, self.duplicate, self.latency = loss, duplicate, latency
        self.queue: List[Any] = []
        self.counter = itertools.count()
        self.stats = {"sent": 0, "lost": 0, "duplicated": 0}

    def send(self, deliver: Callable[[], Any]) -> None:
        self.stats["sent"] += 1
        if self.rng.random() < self.loss:
            self.stats["lost"] += 1
            return
        copies = 2 if self.rng.random() < self.duplicate else 1
        self.stats["duplicated"] += copies - 1
        for _ in range(copies):
            heapq.heappush(self.queue, (self.clock.now + self.rng.uniform(*self.latency), next(self.counter), deliver))

    async def run_until(self, until: float) -> None:
        while self.queue and self.queue[0][0] <= until:
            at, _, deliver = heapq.heappop(self.queue)
            self.clock.now = max(self.clock.now, at)
            result = deliver()
            if asyncio.iscoroutine(result):
                await result
        self.clock.now = max(self.clock.now, until)


class World:
    def __init__(self, root, clock: Clock) -> None:
        self.root, self.clock = root, clock
        self.devices = DeviceStore(root / "devices.json", 600, 75)
        self.boot()

    def boot(self) -> None:
        """(Re)start Core: history and device registry come from disk; sessions do not survive."""
        self.service = SpatialLabService(self.root / "spatial", form_data_dir=self.root / "no-form", interpreter="rules",
                                         monotonic=self.clock.monotonic)
        self.runtime = RemoteRuntime(self.devices, directory=self.root / "remote", spatial=self.service,
                                     config=SessionConfig(stale_after=12, idle_timeout=90),
                                     monotonic=self.clock.monotonic, wall_ms=self.clock.wall_ms)
        self.hub = self.runtime.hub


class VirtualDevice:
    def __init__(self, name: str, world: World, net: Network, rng: random.Random, spatial_id: str, objects: List[str]) -> None:
        self.name, self.world, self.net, self.rng = name, world, net, rng
        self.spatial_id, self.objects = spatial_id, objects
        self.key = DeviceKey()
        self.skew_ms = rng.uniform(-90_000, 90_000)  # device clocks are not synchronized with Core
        self.seq = itertools.count(1)
        self.session_id: Optional[str] = None
        self.token: Optional[str] = None
        self.cursor = 0
        self.replica: Optional[Dict[str, Any]] = None
        self.revision = -1
        self.syncing: Optional[str] = None
        self.buffer: List[Dict[str, Any]] = []
        self.pending: Dict[str, Dict[str, Any]] = {}
        self.poll_sent: Optional[float] = None
        self.gesture: Optional[Dict[str, Any]] = None
        self.stats: Dict[str, int] = {}
        self.sent_commands: Dict[str, Dict[str, Any]] = {}
        code = world.hub.create_pairing_code(scopes.PRESETS["spatial-remote"], name)["code"]
        self.device_id = world.hub.pair(code, name, "phone", self.key.jwk())["device"]["id"]

    def count(self, key: str) -> None:
        self.stats[key] = self.stats.get(key, 0) + 1

    # Session --------------------------------------------------------------------------
    async def handshake(self) -> None:
        hub = self.world.hub
        nonce = hub.challenge(self.device_id)["nonce"]
        welcome = await hub.open_session(self.device_id, nonce=nonce, signature=self.key.proof(self.device_id, nonce),
                                         capabilities=["touch", "display"])
        self.session_id, self.token, self.cursor = welcome["session_id"], welcome["session_token"], 0
        self.pending.clear()
        self.poll_sent = None
        self.gesture = None
        self.count("handshakes")
        self.resync()

    def envelope(self, kind: str, body: Dict[str, Any]) -> Dict[str, Any]:
        seq = next(self.seq)
        return {"v": 1, "id": f"{self.name}-{seq:07d}", "seq": seq, "t": self.world.clock.wall_ms() + self.skew_ms,
                "kind": kind, "body": body}

    def reliable(self, kind: str, body: Dict[str, Any], purpose: str = "") -> str:
        env = self.envelope(kind, body)
        self.pending[env["id"]] = {"env": env, "sent": self.world.clock.now, "tries": 1, "purpose": purpose}
        self.transmit(env)
        return env["id"]

    def realtime(self, kind: str, body: Dict[str, Any]) -> None:
        self.transmit(self.envelope(kind, body))

    def transmit(self, env: Dict[str, Any]) -> None:
        session_id, token = self.session_id, self.token

        async def deliver():
            try:
                session = self.world.hub.authenticate(session_id, token)
            except SessionAuthError as exc:
                response = protocol.error(exc.code, str(exc), re_id=env["id"])
            else:
                response = await self.world.hub.receive(session, copy.deepcopy(env), "sim")
            if response is not None:
                self.net.send(lambda: self.on_response(response, session_id))
        self.net.send(deliver)

    def poll(self) -> None:
        session_id, token, cursor = self.session_id, self.token, self.cursor
        self.poll_sent = self.world.clock.now

        async def deliver():
            try:
                session = self.world.hub.authenticate(session_id, token)
            except SessionAuthError as exc:
                code = exc.code
                self.net.send(lambda: self.on_session_error(code, session_id))
                return
            self.world.hub.sessions.touch(session)
            session.outbox.ack(cursor)
            messages, covered = session.outbox.after(cursor)
            self.net.send(lambda: self.on_poll(copy.deepcopy(messages), covered, cursor, session_id))
        self.net.send(deliver)

    def on_session_error(self, code: str, session_id: Optional[str]) -> None:
        if session_id == self.session_id:
            self.session_id = None  # handshake on the next tick
            self.count("session_lost:" + code)

    # Downlink ---------------------------------------------------------------------------
    def on_poll(self, messages, covered, cursor, session_id) -> None:
        if session_id != self.session_id:
            return
        self.poll_sent = None
        if not covered and cursor == self.cursor:
            self.count("resync_window")
            self.resync()
        for message in messages:
            if message["sseq"] <= self.cursor:
                continue  # a duplicated or late poll response
            self.cursor = message["sseq"]
            self.handle(message)

    def handle(self, message: Dict[str, Any]) -> None:
        kind = message["kind"]
        if kind == "spatial.events":
            if self.syncing:
                self.buffer.append(message)
            else:
                self.apply_events(message["body"]["events"])
        elif kind == "resync_required":
            self.resync()
        elif kind in {"session.closed", "revoked"}:
            self.session_id = None

    def apply_events(self, events: List[Dict[str, Any]]) -> None:
        for event in events:
            if event["seq"] <= self.revision:
                continue
            if event["seq"] != self.revision + 1 or self.replica is None:
                self.count("gap")
                self.resync()
                return
            try:
                self.replica = patches.apply(self.replica, event["patches"])
            except patches.PatchConflict:
                self.count("patch_conflict")
                self.resync()
                return
            self.revision = event["seq"]
            if digest(self.replica) != event["digest_after"]:
                self.count("digest_mismatch")
                self.resync()
                return

    def resync(self) -> None:
        if self.session_id is None:
            return
        body = {"session_id": self.spatial_id}
        if self.replica is not None and self.revision >= 0:
            body.update(revision=self.revision, digest=digest(self.replica))
        self.syncing = self.reliable("spatial.subscribe", body, "sync")

    def apply_sync(self, body: Dict[str, Any]) -> None:
        if body["mode"] == "snapshot":
            self.replica = copy.deepcopy(body["snapshot"]["state"])
            self.revision = body["snapshot"]["session"]["revision"]
            self.count("sync_snapshot")
        else:
            self.count("sync_events")
            self.apply_events(body["events"])
        self.syncing = None
        buffered, self.buffer = self.buffer, []
        for message in buffered:
            self.apply_events(message["body"]["events"])

    # Responses --------------------------------------------------------------------------
    def on_response(self, response: Dict[str, Any], session_id: Optional[str]) -> None:
        if session_id != self.session_id:
            return
        code = response["body"].get("code") if response["kind"] == "error" else None
        if code and code.startswith("session_"):
            self.on_session_error(code, session_id)
            return
        entry = self.pending.get(response.get("re"))
        if entry is None:
            return  # duplicated response
        if response["kind"] == "error" and response["body"].get("retryable"):
            self.count("retryable")
            return  # retried by tick
        del self.pending[response["re"]]
        if response.get("duplicate"):
            self.count("dedup_ack")
        if response["kind"] == "error":
            self.count("error:" + code)
            if entry["purpose"] == "sync":
                self.syncing = None
            if entry["purpose"] == "lease" or entry["purpose"].startswith("gesture"):
                self.gesture = None
            return
        if entry["purpose"] == "sync":
            if response["re"] == self.syncing:
                self.apply_sync(response["body"])
        elif entry["purpose"] == "lease" and self.gesture is not None:
            self.gesture["lease"] = response["body"]["id"]
            self.gesture["base"] = response["body"]["revision"]
        elif entry["purpose"] == "command":
            self.count("applied" if response["body"].get("status") == "applied" else "noop")

    # Behaviour --------------------------------------------------------------------------
    def act(self) -> None:
        if self.session_id is None or self.syncing or self.replica is None:
            return
        target = self.rng.choice(self.objects)
        if target not in self.replica["objects"]:
            return
        if self.gesture is not None:
            lease = self.gesture.get("lease")
            if lease is None:
                return
            self.gesture["frames"] += 1
            x = round(self.rng.uniform(-1.5, 1.5), 3)
            transform = {**IDENTITY, "position": [x, 0.0, 0.0]}
            if self.gesture["frames"] < 6:
                self.realtime("spatial.preview", {"lease_id": lease, "transform": transform})
            else:
                self.command({"type": "object.transform", "target": {"id": self.gesture["object"]}, "mode": "set",
                              "transform": transform, "lease_id": lease}, base=self.gesture["base"], modality="gesture")
                self.gesture = None
            return
        roll = self.rng.random()
        if roll < 0.35:
            self.command({"type": "object.transform", "target": {"id": target}, "mode": "translate",
                          "delta": [round(self.rng.uniform(-0.05, 0.05), 3), 0.0, 0.0]})
        elif roll < 0.7:
            x = round(self.rng.uniform(-1.5, 1.5), 3)
            self.command({"type": "object.transform", "target": {"id": target}, "mode": "set",
                          "transform": {**IDENTITY, "position": [x, 0.0, 0.0]}}, base=self.revision)
        elif roll < 0.8:
            self.command({"type": "object.rename", "target": {"id": target}, "label": f"{self.name} {self.rng.randint(1, 999)}"},
                         base=self.revision)
        else:
            self.gesture = {"object": target, "frames": 0}
            self.reliable("spatial.lease.begin", {"object_id": target, "modality": "touch", "base_revision": self.revision}, "lease")

    def command(self, request: Dict[str, Any], base: Optional[int] = None, modality: str = "touch") -> None:
        body: Dict[str, Any] = {"request": request, "modality": modality}
        if base is not None:
            body.update(base_revision=base, input={"base_revision": base})
        message_id = self.reliable("spatial.command", body, "command")
        self.sent_commands[message_id] = request

    async def tick(self, active: bool) -> None:
        now = self.world.clock.now
        if self.session_id is None:
            try:
                await self.handshake()
            except Exception:
                self.count("handshake_failed")
            return
        for entry in list(self.pending.values()):
            if now - entry["sent"] > 0.4:
                entry["sent"], entry["tries"] = now, entry["tries"] + 1
                self.count("retransmit")
                self.transmit(entry["env"])  # same id and seq: Core answers from its cache if it was applied
        if self.poll_sent is None or now - self.poll_sent > 0.5:
            self.poll()
        if self.gesture is not None and self.gesture.get("lease") and self.gesture["frames"] % 3 == 0:
            self.realtime("spatial.lease.renew", {"lease_id": self.gesture["lease"]})
        if active and self.rng.random() < 0.25:
            self.act()

    def settled(self) -> bool:
        return (self.session_id is not None and not self.pending and not self.syncing
                and self.revision == self.world.service.session(self.spatial_id).history.revision)


class NetworkSimulationTests(unittest.TestCase):
    def simulate(self, seed: int, *, devices=3, loss=0.08, duplicate=0.08, seconds=30.0, restart_at: Optional[float] = None,
                 drop_device_at: Optional[float] = None):
        root = temporary_root(self)
        clock = Clock()
        rng = random.Random(seed)
        world = World(root, clock)
        spatial_id = world.service.create_session("Simulation")["session"]["id"]
        objects = []
        for _ in range(3):
            added = world.service.submit_sync(spatial_id, {"type": "scene.add_asset", "fixture": "calibration"}, {"kind": "ui", "provider": "seed"})
            objects.append(added["targets"][0])
        net = Network(rng, clock, loss=loss, duplicate=duplicate)
        clients = [VirtualDevice(f"device{i}", world, net, random.Random(seed * 100 + i), spatial_id, objects) for i in range(devices)]

        async def main():
            step, sweep_every = 0.02, 0.5
            end = clock.now + seconds
            next_sweep = clock.now
            restarted = dropped = False
            while clock.now < end:
                if restart_at is not None and not restarted and clock.now >= 1000.0 + restart_at:
                    world.boot()  # Core restarts: sessions are gone, history and devices persist
                    restarted = True
                if drop_device_at is not None and not dropped and clock.now >= 1000.0 + drop_device_at:
                    clients[0].session_id = "gone"  # the device sleeps; its old session expires in Core
                    dropped = True
                for client in clients:
                    await client.tick(active=True)
                if clock.now >= next_sweep:
                    await world.runtime.sweep()
                    next_sweep = clock.now + sweep_every
                await net.run_until(clock.now + step)
            # Quiesce: the network heals, devices stop acting and must converge.
            net.loss = net.duplicate = 0.0
            deadline = clock.now + 30.0
            while clock.now < deadline and not all(c.settled() and c.gesture is None for c in clients):
                for client in clients:
                    if client.gesture is not None and client.gesture.get("lease") is None and not client.pending:
                        client.gesture = None
                    await client.tick(active=False)
                if clock.now >= next_sweep:
                    await world.runtime.sweep()
                    next_sweep = clock.now + sweep_every
                await net.run_until(clock.now + 0.05)
            clock.advance(5.0)  # any lease a device still held expires
            await world.runtime.sweep()

        asyncio.run(main())
        return world, clients, spatial_id, net

    def assert_invariants(self, world, clients, spatial_id, net):
        history = world.service.session(spatial_id).history
        # 1. Convergence: every device holds exactly Core's state.
        for client in clients:
            self.assertTrue(client.settled(), f"{client.name} did not settle: {client.stats}")
            self.assertEqual(digest(client.replica), history.digest(), client.name)
        # 2. Nothing applied twice: each device message produced at most one history event.
        remote_ids = [(e["origin"]["remote"]["device_id"], e["origin"]["remote"]["message_id"])
                      for e in history.events if e["origin"].get("kind") == "remote"]
        self.assertEqual(len(remote_ids), len(set(remote_ids)))
        # 3. No stale absolute write: an applied 'set'/rename based on revision b had no other change to its object after b.
        for event in history.events:
            base = (event["origin"].get("input") or {}).get("base_revision")
            if base is None or event["origin"].get("kind") != "remote":
                continue
            for other in history.events[base:event["seq"] - 1]:
                if other.get("category") in {"selection", "view"}:
                    continue
                self.assertFalse(set(other["targets"]) & set(event["targets"]),
                                 f"event {event['seq']} (base {base}) overwrote change {other['seq']}")
        # 4. Deterministic replay of the whole history.
        self.assertTrue(history.verify_replay().verified)
        # 5. Nobody still holds an object.
        self.assertEqual(world.service.leases(spatial_id), [])
        # 6. Stale input never reached the scene; the faults actually happened.
        self.assertGreater(net.stats["lost"], 0)
        self.assertGreater(net.stats["duplicated"], 0)
        self.assertTrue(world.runtime.audit.verify()["verified"])
        return history

    def test_lossy_duplicating_reordering_network_converges_without_double_or_stale_writes(self):
        for seed in (1, 2, 3):
            with self.subTest(seed=seed):
                world, clients, spatial_id, net = self.simulate(seed)
                history = self.assert_invariants(world, clients, spatial_id, net)
                totals: Dict[str, int] = {}
                for client in clients:
                    for key, value in client.stats.items():
                        totals[key] = totals.get(key, 0) + value
                self.assertGreater(totals.get("retransmit", 0), 0)
                self.assertGreater(totals.get("error:stale_state", 0), 0, totals)  # stale writes were refused, not applied
                self.assertGreater(len(history.events), 20)

    def test_core_restart_mid_session_devices_rehandshake_and_resync(self):
        world, clients, spatial_id, net = self.simulate(7, loss=0.05, duplicate=0.05, seconds=24.0, restart_at=10.0)
        self.assert_invariants(world, clients, spatial_id, net)
        for client in clients:
            self.assertGreaterEqual(client.stats.get("handshakes", 0), 2, client.stats)
            self.assertTrue(any(key.startswith("session_lost:session_unknown") for key in client.stats), client.stats)

    def test_sleeping_device_expires_and_recovers_with_a_new_session(self):
        world, clients, spatial_id, net = self.simulate(11, loss=0.03, duplicate=0.03, seconds=20.0, drop_device_at=5.0)
        self.assert_invariants(world, clients, spatial_id, net)
        self.assertGreaterEqual(clients[0].stats.get("handshakes", 0), 2)

    def test_same_seed_same_outcome(self):
        def shape(run):
            world, clients, spatial_id, net = run
            events = world.service.session(spatial_id).history.events
            return ([(e["seq"], e["kind"], e["command"]["type"], e["origin"].get("remote", {}).get("message_id")) for e in events],
                    net.stats, [c.stats for c in clients])
        # Object and session ids are random; everything the seed controls must repeat exactly.
        self.assertEqual(shape(self.simulate(5, seconds=8.0)), shape(self.simulate(5, seconds=8.0)))


if __name__ == "__main__":
    unittest.main()
