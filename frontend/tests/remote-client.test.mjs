// Remote presence client: session resilience, Spatial sync, touch input, identity contract.
// Deterministic: a manual clock and in-memory transports stand in for timers and the network.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { RemoteSessionClient } from "../src/lib/remote/session.ts";
import { RemoteSpatial, modalityFor } from "../src/lib/remote/spatial.ts";
import { HttpTransport } from "../src/lib/remote/transport.ts";
import { base64url, proofMessage, signProof, publicJwk } from "../src/lib/remote/identity.ts";
import { RemoteFailure } from "../src/lib/remote/protocol.ts";
import { SpatialSceneStore } from "../src/lib/spatial/scene-store.ts";
import { SpatialGestureController } from "../src/lib/spatial/controller.ts";
import { TouchHandProvider, touchGestureConfig } from "../src/lib/spatial/providers/touch.ts";
import { GesturePipeline } from "../src/lib/spatial/gesture/pipeline.ts";
import { PerspectiveProjector, DEFAULT_RIG } from "../src/lib/spatial/projection.ts";

const contracts = new URL("../../shared/contracts/remote/", import.meta.url);
const flush = () => new Promise((resolve) => setImmediate(resolve));

class ManualClock {
  constructor() { this.t = 0; this.timers = []; this.n = 0; }
  now() { return this.t; }
  wall() { return 1_700_000_000_000 + this.t; }
  setTimeout(fn, ms) { const h = { at: this.t + ms, fn, id: ++this.n }; this.timers.push(h); return h; }
  clearTimeout(h) { this.timers = this.timers.filter((x) => x !== h); }
  async advance(ms) {
    const end = this.t + ms;
    for (;;) {
      await flush();
      const due = this.timers.filter((h) => h.at <= end).sort((a, b) => a.at - b.at || a.id - b.id)[0];
      if (!due) break;
      this.timers = this.timers.filter((h) => h !== due);
      this.t = due.at;
      due.fn();
    }
    this.t = end;
    await flush();
  }
}

/** Core's message rules in miniature: idempotency by id, strict seq order, pings. */
class FakeCore {
  constructor() { this.sessions = 0; this.applied = []; this.cache = new Map(); this.lastSeq = 0; this.revoked = false; this.reject = null; }
  handshake() {
    if (this.reject) return Promise.reject(this.reject);
    this.sessions += 1;
    this.cache = new Map();
    this.lastSeq = 0;
    return Promise.resolve({ session_id: `rs-${String(this.sessions).padStart(16, "0")}`, session_token: `token-${this.sessions}`,
      kind: "device", device: { id: "d", name: "Phone", device_type: "phone", kind: "device" }, scopes: ["spatial.view", "spatial.control"],
      protocol: "akashi.remote/1", server_time_ms: 0, heartbeat_ms: 5000, stale_after_ms: 12000, idle_timeout_ms: 90000, max_lifetime_ms: 3600000,
      endpoints: [], limits: { max_message_bytes: 65536, max_batch: 32 } });
  }
  receive(env) {
    if (env.kind === "ping") return { v: 1, kind: "ack", re: env.id, seq: env.seq, body: { server_ms: 1 } };
    if (this.cache.has(env.id)) return { ...this.cache.get(env.id), duplicate: true };
    // Like Core: a rate-limited message is refused before ordering and is not consumed.
    if (env.body.fail === "rate_limited") return { v: 1, kind: "error", re: env.id, seq: env.seq, body: { code: "rate_limited", message: "slow down", retryable: true } };
    if (env.seq <= this.lastSeq) return { v: 1, kind: "error", re: env.id, seq: env.seq, body: { code: "out_of_order", message: "old", retryable: false } };
    this.lastSeq = env.seq;
    if (env.body.fail) return { v: 1, kind: "error", re: env.id, seq: env.seq, body: { code: env.body.fail, message: "x", retryable: env.body.fail === "rate_limited" } };
    this.applied.push(env.body.value);
    const ack = { v: 1, kind: "ack", re: env.id, seq: env.seq, body: { value: env.body.value } };
    this.cache.set(env.id, ack);
    return ack;
  }
}

class Link {
  constructor(core, clock) { this.core = core; this.clock = clock; this.up = true; this.dropUp = false; this.dropDown = false; this.opened = []; this.transports = []; }
  factory(name = "websocket") {
    return (events) => this.transport(name, events);
  }
  transport(name, events) {
    const link = this;  // eslint-disable-line @typescript-eslint/no-this-alias -- object-literal methods below need the link
    {
      const transport = {
        name, open(auth) {
          link.opened.push(auth);
          if (!link.up) { link.clock.setTimeout(() => events.onClose(1006, "down"), 10); return; }
          link.clock.setTimeout(() => events.onOpen({ resumed: auth.resumeAfter !== null, body: {} }), 5);
          transport.events = events;
        },
        send(envs) {
          if (!link.up) return false;
          for (const env of envs) {
            if (link.dropUp) continue;
            const response = link.core.receive(env);
            if (!link.dropDown) link.clock.setTimeout(() => events.onMessage(response), 20);
          }
          return true;
        },
        close() {}, events: null,
        push(message) { events.onMessage(message); },
        drop(code = 1006) { events.onClose(code, "dropped"); },
      };
      link.transports.push(transport);
      return transport;
    }
  }
  get current() { return this.transports.at(-1); }
}

function setup(options = {}) {
  const clock = new ManualClock();
  const core = new FakeCore();
  const link = new Link(core, clock);
  const client = new RemoteSessionClient({ clock, random: () => 0.5, handshake: () => core.handshake(),
    transports: options.transports ?? [{ name: "websocket", create: link.factory("websocket") }], attemptTimeoutMs: 1000, requestDeadlineMs: 8000 });
  return { clock, core, link, client };
}

test("reliable requests resolve once; a lost reply is retried with the same id and answered from Core's cache", async () => {
  const { clock, core, link, client } = setup();
  client.start();
  await clock.advance(50);
  assert.equal(client.state, "online");
  link.dropDown = true;
  const result = client.request("test", { value: "A" });
  await clock.advance(500);
  link.dropDown = false;
  await clock.advance(1200);  // attempt timer resends the same envelope
  assert.deepEqual(await result, { value: "A" });
  assert.deepEqual(core.applied, ["A"]);
  assert.equal(client.metrics().duplicatesAcked, 1);
  assert.ok(client.metrics().retransmits >= 1);
});

test("a request that never gets an answer fails at its deadline instead of hanging", async () => {
  const { clock, link, client } = setup();
  client.start();
  await clock.advance(50);
  link.dropUp = true;
  const result = client.request("test", { value: "B" }).catch((error) => error);
  await clock.advance(9000);
  const error = await result;
  assert.ok(error instanceof RemoteFailure);
  assert.equal(error.code, "timeout");
});

test("disconnect: backoff, resume after the last cursor, unanswered requests resent unchanged", async () => {
  const { clock, core, link, client } = setup();
  client.start();
  await clock.advance(50);
  link.current.push({ v: 1, sseq: 7, kind: "x", body: {} });
  link.up = false;
  link.current.drop();
  assert.equal(client.state, "reconnecting");
  const pending = client.request("test", { value: "C" });  // made while offline: queued, sent on reconnect
  await clock.advance(3000);
  link.up = true;
  await clock.advance(20_000);
  assert.equal(client.state, "online");
  assert.equal(link.opened.at(-1).resumeAfter, 7);
  assert.equal(core.sessions, 1, "same session resumed, no new handshake");
  assert.deepEqual(await pending, { value: "C" });
  assert.deepEqual(core.applied, ["C"]);
});

test("a replaced session fails in-flight requests as outcome_unknown and never resends them", async () => {
  const { clock, core, link, client } = setup();
  const sessions = [];
  client.onSession((welcome, resumed) => sessions.push([welcome.session_id, resumed]));
  client.start();
  await clock.advance(50);
  link.dropDown = true;
  const inflight = client.request("test", { value: "D" }).catch((error) => error);
  await clock.advance(10);
  link.dropDown = false;
  link.current.drop(4401);  // Core restarted / session expired
  await clock.advance(5000);
  const error = await inflight;
  assert.equal(error.code, "outcome_unknown");
  assert.equal(core.sessions, 2);
  assert.deepEqual(core.applied, ["D"], "applied once by the old session; not resent to the new one");
  assert.deepEqual(sessions.map(([, resumed]) => resumed), [false, false]);
});

test("revocation stops the client; an unknown device becomes unpaired", async () => {
  const { clock, link, client } = setup();
  client.start();
  await clock.advance(50);
  link.current.push({ v: 1, sseq: 3, kind: "revoked", body: { reason: "The owner revoked this device." } });
  assert.equal(client.state, "revoked");
  const second = setup();
  second.core.reject = new RemoteFailure("device_unknown", "Unknown device");
  second.client.start();
  await second.clock.advance(100);
  assert.equal(second.client.state, "unpaired");
});

test("retryable errors (rate limits) are retried; non-retryable errors reject", async () => {
  const { clock, client } = setup();
  client.start();
  await clock.advance(50);
  const rejected = client.request("test", { fail: "forbidden" }).catch((error) => error);
  await clock.advance(100);
  assert.equal((await rejected).code, "forbidden");
  const limited = client.request("test", { fail: "rate_limited" }).catch((error) => error);
  await clock.advance(100);
  let settled = false;
  limited.then(() => { settled = true; });
  await flush();
  assert.equal(settled, false, "kept pending for retry");
  await clock.advance(9000);
  assert.equal((await limited).code, "rate_limited");
});

test("silence beyond stale_after forces a reconnect even if the socket never reported closing", async () => {
  const { clock, link, client } = setup();
  client.start();
  await clock.advance(50);
  link.dropDown = true;  // e.g. Wi-Fi switched; the socket looks alive but nothing arrives
  await clock.advance(19_000);
  assert.ok(client.metrics().reconnects >= 1);
  link.dropDown = false;
  await clock.advance(20_000);
  assert.equal(client.state, "online");
});

test("realtime input is never queued while offline", async () => {
  const { clock, link, client } = setup();
  client.start();
  await clock.advance(50);
  link.up = false;
  link.current.drop();
  assert.equal(client.send("spatial.preview", { x: 1 }), false);
});

test("WebSocket failing twice falls back to the HTTP transport", async () => {
  const clock = new ManualClock();
  const core = new FakeCore();
  const ws = new Link(core, clock);
  ws.up = false;
  const http = new Link(core, clock);
  const client = new RemoteSessionClient({ clock, random: () => 0.5, handshake: () => core.handshake(),
    transports: [{ name: "websocket", create: ws.factory("websocket") }, { name: "http", create: http.factory("http") }] });
  client.start();
  await clock.advance(10_000);
  assert.equal(client.state, "online");
  assert.equal(client.metrics().transport, "http");
});

test("HTTP transport: cursor long-poll, serialized uplink, 401 maps to re-handshake", async () => {
  const calls = [];
  let polls = 0;
  const request = async (path, init) => {
    calls.push([init.method, path]);
    if (init.method === "POST") return { status: 200, json: { responses: init.body.messages.map((m) => ({ v: 1, kind: "ack", re: m.id, body: {} })) } };
    polls += 1;
    if (polls === 1) return { status: 200, json: { messages: [{ v: 1, sseq: 4, kind: "x", body: {} }], resync: false, state: "open" } };
    if (polls === 2) return { status: 200, json: { messages: [{ v: 1, sseq: 4, kind: "x", body: {} }, { v: 1, sseq: 6, kind: "y", body: {} }], resync: true, state: "open" } };
    return { status: 401, json: { code: "session_expired" } };
  };
  const received = [];
  const closes = [];
  const transport = new HttpTransport(request, { onOpen() {}, onMessage: (m) => received.push(m.kind), onClose: (code, reason) => closes.push([code, reason]) }, 0);
  transport.open({ sessionId: "rs-1", token: "t", resumeAfter: null });
  transport.send([{ v: 1, id: "aaaaaaaa", seq: 1, t: 0, kind: "k", body: {} }]);
  for (let i = 0; i < 10; i += 1) await flush();
  // Uplink acks and downlink pushes travel on separate requests; only the downlink order is defined.
  assert.deepEqual(received.filter((kind) => kind !== "ack"), ["x", "resync_required", "y"]);
  assert.equal(received.filter((kind) => kind === "ack").length, 1);
  assert.deepEqual(closes, [[4401, "session_expired"]]);
  assert.ok(calls.some(([, path]) => path.includes("after=4")));
});

// Spatial ---------------------------------------------------------------------------------
function fakeChannel() {
  const handlers = new Map();
  const sessionHandlers = new Set();
  const requests = [];
  const sent = [];
  const clock = new ManualClock();
  return {
    clock, requests, sent, state: "online",
    on(kind, handler) { if (!handlers.has(kind)) handlers.set(kind, new Set()); handlers.get(kind).add(handler); return () => handlers.get(kind).delete(handler); },
    onSession(handler) { sessionHandlers.add(handler); return () => sessionHandlers.delete(handler); },
    emit(kind, body) { for (const handler of handlers.get(kind) ?? []) handler({ v: 1, kind, body }); },
    request(kind, body) { return new Promise((resolve, reject) => requests.push({ kind, body, resolve, reject })); },
    send(kind, body) { sent.push({ kind, body }); return true; },
  };
}

const object = (x) => ({ id: "obj-1", label: "Box", transform: { position: [x, 0, 0], rotation: [0, 0, 0, 1], scale: 1 }, visible: true });
const scene = (x) => ({ objects: { "obj-1": object(x) }, order: ["obj-1"], selection: [], inspector: null, view: {} });
const info = (revision) => ({ id: "spatial-1", label: "Desk", revision, digest: `d${revision}`, can_undo: true, can_redo: false, leases: [],
  pending_confirmations: [], presence_fresh: false, recovered_torn_tail: false });
const moveEvent = (seq, from, to) => ({ seq, kind: "command", category: "transform", at: "", command: "object.transform", targets: ["obj-1"], summary: "",
  patches: [{ op: "replace", path: ["objects", "obj-1", "transform", "position"], before: [from, 0, 0], after: [to, 0, 0] }],
  digest_before: `d${seq - 1}`, digest_after: `d${seq}`, undoes: null, redoes: null, origin: { kind: "remote", en: "Remote touch from Phone", tr: "" } });

function syncAck(revision, x) {
  return { session_id: "spatial-1", mode: "snapshot", snapshot: { session: info(revision), state: scene(x) }, revision, digest: `d${revision}`,
    leases: [], previews: [], roster: [], session: info(revision) };
}

test("spatial sync: snapshot, ordered events, duplicates ignored, gap → re-sync with revision and digest", async () => {
  const channel = fakeChannel();
  const store = new SpatialSceneStore();
  const spatial = new RemoteSpatial(channel, store, { sessionId: "spatial-1" });
  spatial.start();
  assert.equal(channel.requests[0].kind, "spatial.subscribe");
  channel.emit("spatial.events", { events: [moveEvent(6, 0, 9)] });  // arrives during sync: buffered
  channel.requests[0].resolve(syncAck(5, 0));
  await flush();
  assert.equal(store.revision, 6);
  assert.deepEqual(store.view().objects["obj-1"].transform.position, [9, 0, 0]);
  channel.emit("spatial.events", { events: [moveEvent(6, 0, 9), moveEvent(7, 9, 1)] });
  assert.equal(store.revision, 7);
  channel.emit("spatial.events", { events: [moveEvent(9, 3, 4)] });  // revision 8 is missing
  assert.equal(store.revision, 7, "never applied across a gap");
  const resync = channel.requests.at(-1);
  assert.equal(resync.kind, "spatial.subscribe");
  assert.deepEqual([resync.body.revision, resync.body.digest], [7, "d7"]);
});

test("spatial sync: an inconsistent patch is never drawn; it triggers a re-sync", async () => {
  const channel = fakeChannel();
  const store = new SpatialSceneStore();
  const spatial = new RemoteSpatial(channel, store, { sessionId: "spatial-1" });
  spatial.start();
  channel.requests[0].resolve(syncAck(5, 0));
  await flush();
  channel.emit("spatial.events", { events: [moveEvent(6, 42, 1)] });  // "before" does not match the replica
  assert.equal(store.revision, 5);
  assert.equal(channel.requests.length, 2);
});

test("remote previews show other devices' live manipulation and end with the lease", async () => {
  const channel = fakeChannel();
  const store = new SpatialSceneStore();
  const spatial = new RemoteSpatial(channel, store, { sessionId: "spatial-1" });
  spatial.start();
  channel.requests[0].resolve(syncAck(5, 0));
  await flush();
  channel.emit("spatial.preview", { lease_id: "lease-1", object_id: "obj-1", transform: { position: [2, 0, 0], rotation: [0, 0, 0, 1], scale: 1 } });
  assert.deepEqual(store.view().objects["obj-1"].transform.position, [2, 0, 0]);
  assert.ok(spatial.isRemotelyHeld("obj-1"));
  channel.emit("spatial.leases", { leases: [] });  // the holder disconnected: back to the committed state
  assert.deepEqual(store.view().objects["obj-1"].transform.position, [0, 0, 0]);
});

test("a remote command resolves only when the committed event is in the replica (no snap-back)", async () => {
  const channel = fakeChannel();
  const store = new SpatialSceneStore();
  const spatial = new RemoteSpatial(channel, store, { sessionId: "spatial-1" });
  spatial.start();
  channel.requests[0].resolve(syncAck(5, 0));
  await flush();
  let done = false;
  const result = spatial.command({ type: "object.transform", target: { id: "obj-1" }, mode: "translate", delta: [1, 0, 0] }, "touch").then((r) => { done = true; return r; });
  const sent = channel.requests.at(-1);
  assert.deepEqual([sent.kind, sent.body.base_revision, sent.body.modality], ["spatial.command", 5, "touch"]);
  sent.resolve({ status: "applied", revision: 6, targets: ["obj-1"], notes: [] });
  await flush();
  assert.equal(done, false, "waits for the event");
  channel.emit("spatial.events", { events: [moveEvent(6, 0, 1)] });
  const value = await result;
  assert.equal(value.snapshot.session.revision, 6);
});

test("gesture controller over the remote port: one lease, throttled previews, one commit", async () => {
  const channel = fakeChannel();
  const store = new SpatialSceneStore();
  const spatial = new RemoteSpatial(channel, store, { sessionId: "spatial-1", modality: () => "touch" });
  spatial.start();
  channel.requests[0].resolve(syncAck(5, 0));
  await flush();
  let now = 0;
  const controller = new SpatialGestureController({ api: spatial.port(), store, sessionId: () => "spatial-1", provider: () => "touch",
    onError: () => {}, onRefused: () => {}, now: () => now, every: () => () => {} });
  const transform = (x) => ({ position: [x, 0, 0], rotation: [0, 0, 0, 1], scale: 1 });
  controller.handle([{ type: "manipulation.begin", objectId: "obj-1", hand: 1, transform: transform(0) }]);
  await flush();
  const begin = channel.requests.at(-1);
  assert.equal(begin.kind, "spatial.lease.begin");
  begin.resolve({ id: "lease-9", object_id: "obj-1", origin: "remote:touch", expires_in: 4, revision: 5 });
  await flush();
  for (let i = 1; i <= 10; i += 1) {
    now += 10;  // 100 Hz updates
    controller.handle([{ type: "manipulation.update", objectId: "obj-1", hand: 1, transform: transform(i / 10) }]);
  }
  const previews = channel.sent.filter((m) => m.kind === "spatial.preview");
  assert.ok(previews.length >= 2 && previews.length <= 4, `throttled to ~30 Hz, got ${previews.length}`);
  assert.equal(previews[0].body.lease_id, "lease-9");
  controller.handle([{ type: "manipulation.end", objectId: "obj-1", hand: 1, transform: transform(1), reason: "release", provenance: { hand: "Right" } }]);
  await flush();
  const commit = channel.requests.at(-1);
  assert.deepEqual([commit.kind, commit.body.request.mode, commit.body.request.lease_id, commit.body.modality], ["spatial.command", "set", "lease-9", "touch"]);
});

test("modality mapping from origins", () => {
  assert.equal(modalityFor({ kind: "language", provider: "x", input: { voice: true } }), "voice");
  assert.equal(modalityFor({ kind: "ui", provider: "x" }), "ui");
  assert.equal(modalityFor({ kind: "gesture", provider: "touch" }), "touch");
});

// Touch -----------------------------------------------------------------------------------
test("touch: one finger drags and commits once, through the same gesture pipeline", () => {
  let t = 0;
  const clock = { now: () => t, every: () => () => {} };
  const projector = new PerspectiveProjector(DEFAULT_RIG, 16 / 9);
  const identity = (p) => ({ x: p.x, y: p.y });
  const surface = { getBoundingClientRect: () => ({ left: 0, top: 0, width: 1280, height: 720 }) };
  const touch = new TouchHandProvider(surface, identity, clock);
  const object = { id: "obj-1", transform: { position: [0, 0, 0], rotation: [0, 0, 0, 1], scale: 1 }, size: [0.5, 1.7, 0.3], visible: true };
  const view = { objects: [object], selection: [], limits: { position_min: [-4, -1, -4], position_max: [4, 4, 2], scale_min: 0.1, scale_max: 10 } };
  const pipeline = new GesturePipeline(touchGestureConfig(), projector, () => false, () => 0);
  const chest = projector.project([0, 1.0, 0]);
  const intents = [];
  const step = () => { t += 16; intents.push(...pipeline.process(touch.frame(), view, identity).intents.filter((i) => i.type !== "hover")); };
  const at = (x, y) => ({ pointerId: 1, clientX: x * 1280, clientY: y * 720 });
  touch.down(at(chest.x, chest.y));
  step();
  for (let i = 1; i <= 25; i += 1) { touch.move(at(chest.x + 0.008 * i, chest.y)); step(); }
  for (let i = 0; i < 6; i += 1) step();
  touch.up(at(chest.x + 0.2, chest.y));
  for (let i = 0; i < 8; i += 1) step();
  const kinds = intents.map((intent) => intent.type);
  assert.equal(kinds.filter((k) => k === "manipulation.begin").length, 1, kinds.join(","));
  assert.equal(kinds.filter((k) => k === "manipulation.end").length, 1, kinds.join(","));
  const end = intents.find((i) => i.type === "manipulation.end");
  assert.equal(end.reason, "release");
  assert.ok(end.transform.position[0] > 0.1, `moved right: ${end.transform.position[0]}`);
  assert.equal(touch.activeTouches, 0);
});

test("touch: a quick tap selects without moving", () => {
  let t = 0;
  const clock = { now: () => t, every: () => () => {} };
  const projector = new PerspectiveProjector(DEFAULT_RIG, 16 / 9);
  const identity = (p) => ({ x: p.x, y: p.y });
  const touch = new TouchHandProvider({ getBoundingClientRect: () => ({ left: 0, top: 0, width: 1280, height: 720 }) }, identity, clock);
  const object = { id: "obj-1", transform: { position: [0, 0, 0], rotation: [0, 0, 0, 1], scale: 1 }, size: [0.5, 1.7, 0.3], visible: true };
  const view = { objects: [object], selection: [], limits: { position_min: [-4, -1, -4], position_max: [4, 4, 2], scale_min: 0.1, scale_max: 10 } };
  const pipeline = new GesturePipeline(touchGestureConfig(), projector, () => false, () => 0);
  const chest = projector.project([0, 1.0, 0]);
  const intents = [];
  const step = () => { t += 16; intents.push(...pipeline.process(touch.frame(), view, identity).intents.filter((i) => i.type !== "hover")); };
  touch.down({ pointerId: 7, clientX: chest.x * 1280, clientY: chest.y * 720 });
  for (let i = 0; i < 6; i += 1) step();  // ~100 ms touch
  touch.up({ pointerId: 7 });
  for (let i = 0; i < 8; i += 1) step();
  assert.deepEqual(intents.map((i) => i.type), ["select"]);
});

// Identity contract -------------------------------------------------------------------------
test("identity: the proof format and signature match Core's (shared fixture verified by Python too)", async () => {
  const fixture = JSON.parse(readFileSync(new URL("handshake-fixture.json", contracts)));
  assert.equal(proofMessage(fixture.device_id, fixture.nonce, fixture.scopes), fixture.message);
  assert.equal(proofMessage(fixture.device_id, fixture.nonce, null), fixture.message_all_scopes);
  const subtle = globalThis.crypto.subtle;
  const key = await subtle.importKey("jwk", { ...fixture.public_jwk, ext: true }, { name: "ECDSA", namedCurve: "P-256" }, true, ["verify"]);
  const raw = Uint8Array.from(atob(fixture.signature.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));
  assert.ok(await subtle.verify({ name: "ECDSA", hash: "SHA-256" }, key, raw, new TextEncoder().encode(fixture.message)));
  // A fresh device key is non-extractable: only the public half can leave the device.
  const keys = await subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, false, ["sign", "verify"]);
  await assert.rejects(subtle.exportKey("jwk", keys.privateKey));
  const jwk = await publicJwk(keys, subtle);
  assert.deepEqual(Object.keys(jwk).sort(), ["crv", "kty", "x", "y"]);
  assert.match(await signProof(keys, "d", "n", null, subtle), /^[A-Za-z0-9_-]{86}$/);
  assert.equal(base64url(new Uint8Array([251, 255])), "-_8");
});

test("protocol contract: client scope labels cover Core's scopes", () => {
  const protocol = JSON.parse(readFileSync(new URL("protocol.json", contracts)));
  return import("../src/lib/remote/protocol.ts").then(({ SCOPE_LABELS, PROTOCOL }) => {
    assert.equal(protocol.protocol, PROTOCOL);
    assert.deepEqual(Object.keys(SCOPE_LABELS).sort(), protocol.scopes.map((s) => s.scope).sort());
    assert.ok(protocol.kinds["spatial.preview"].delivery === "realtime");
  });
});
