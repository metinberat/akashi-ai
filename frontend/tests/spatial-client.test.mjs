// Spatial Lab client logic: backend contract, replay reconstruction, scene
// replica store, gesture→command controller and recordings.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { applyPatches, reconstruct, ReplayInconsistent } from "../src/lib/spatial/replay.ts";
import { SpatialSceneStore } from "../src/lib/spatial/scene-store.ts";
import { SpatialGestureController } from "../src/lib/spatial/controller.ts";
import { HandRecorder, RecordingInvalid, recordingFrames, validateRecording, RECORDING_SCHEMA } from "../src/lib/spatial/providers/recorded.ts";
import { OPEN_RIGHT, syntheticHand } from "../src/lib/spatial/gesture/synthetic.ts";
import { gestureConfig } from "../src/lib/spatial/gesture/config.ts";
import { GesturePipeline } from "../src/lib/spatial/gesture/pipeline.ts";
import { PerspectiveProjector, DEFAULT_RIG } from "../src/lib/spatial/projection.ts";

const contracts = new URL("../../shared/contracts/spatial/", import.meta.url);
const schema = JSON.parse(readFileSync(new URL("requests.schema.json", contracts)));
const fixture = JSON.parse(readFileSync(new URL("replay-fixture.json", contracts)));

// Minimal validator for the pydantic-generated schema subset (refs, discriminated
// unions, anyOf for optionals, closed objects, enums/consts, numeric bounds).
function validate(value, node, path = "$") {
  if (node.$ref) return validate(value, schema.$defs[node.$ref.split("/").pop()], path);
  if (node.discriminator) {
    const target = node.discriminator.mapping[value?.[node.discriminator.propertyName]];
    if (!target) return [`${path}: unknown ${node.discriminator.propertyName} ${value?.type}`];
    return validate(value, { $ref: target }, path);
  }
  if (node.anyOf) return node.anyOf.some((option) => validate(value, option, path).length === 0) ? [] : [`${path}: no anyOf branch matched`];
  const errors = [];
  if (node.const !== undefined && value !== node.const) errors.push(`${path}: expected ${node.const}`);
  if (node.enum && !node.enum.includes(value)) errors.push(`${path}: not in enum`);
  const types = { object: (v) => v && typeof v === "object" && !Array.isArray(v), array: Array.isArray, string: (v) => typeof v === "string",
    number: (v) => typeof v === "number" && Number.isFinite(v), integer: Number.isInteger, boolean: (v) => typeof v === "boolean", null: (v) => v === null };
  if (node.type && !types[node.type](value)) return [`${path}: expected ${node.type}`];
  if (node.type === "number" || node.type === "integer") {
    if (node.minimum !== undefined && value < node.minimum) errors.push(`${path}: below minimum`);
    if (node.maximum !== undefined && value > node.maximum) errors.push(`${path}: above maximum`);
    if (node.exclusiveMinimum !== undefined && value <= node.exclusiveMinimum) errors.push(`${path}: not above exclusiveMinimum`);
  }
  if (node.type === "string" && node.maxLength !== undefined && value.length > node.maxLength) errors.push(`${path}: too long`);
  if (node.type === "object") {
    for (const key of node.required ?? []) if (!(key in value)) errors.push(`${path}.${key}: required`);
    for (const [key, item] of Object.entries(value)) {
      if (node.properties?.[key]) errors.push(...validate(item, node.properties[key], `${path}.${key}`));
      else if (node.additionalProperties === false) errors.push(`${path}.${key}: unexpected`);
    }
  }
  if (node.type === "array" && node.items) value.forEach((item, i) => errors.push(...validate(item, node.items, `${path}[${i}]`)));
  return errors;
}

test("requests built by the frontend satisfy the backend's generated schema", () => {
  const transform = { position: [0.4, 0.1, 0], rotation: [0, 0, 0, 1], scale: 1.1 };
  const requests = [
    { type: "object.transform", target: { id: "obj-000000000001" }, mode: "set", transform, lease_id: "lease-abc" },
    { type: "selection.select", target: { id: "obj-000000000001" } },
    { type: "selection.select" },
    { type: "scene.add_asset", form: { project_id: "p1", version: "latest" } },
    { type: "scene.add_asset", fixture: "calibration" },
    { type: "object.display", target: { ref: "selected" }, skeleton: true },
    { type: "animation.control", target: { ref: "selected" }, action: "play", clip: "Idle" },
    { type: "object.version", target: { ref: "form" }, version: "previous" },
    { type: "view.set", hud_visible: false },
    { type: "history.undo" },
  ];
  for (const request of requests) assert.deepEqual(validate(request, schema), [], JSON.stringify(request));
  assert.notDeepEqual(validate({ type: "object.transform", target: { id: "x" }, mode: "set", transform, extra: 1 }, schema), []);
  assert.notDeepEqual(validate({ type: "object.explode" }, schema), []);
});

test("client replay reconstructs the backend fixture exactly, including undo/redo", () => {
  const frames = reconstruct(fixture.initial_state, fixture.events);
  assert.equal(frames.length, fixture.events.length + 1);
  assert.deepEqual(frames.at(-1).state, fixture.final_state);
  const undo = fixture.events.find((e) => e.kind === "undo");
  assert.ok(frames[undo.seq].state !== frames[undo.seq - 1].state);
});

test("corrupted replay data is rejected instead of drawn", () => {
  const events = structuredClone(fixture.events);
  const transform = events.find((e) => e.command.type === "object.transform");
  transform.patches[0].before = { position: [9, 9, 9], rotation: [0, 0, 0, 1], scale: 1 };
  assert.throws(() => reconstruct(fixture.initial_state, events), ReplayInconsistent);
  const gap = structuredClone(fixture.events);
  gap.splice(2, 1);
  assert.throws(() => reconstruct(fixture.initial_state, gap), /not contiguous/);
  assert.throws(() => applyPatches({ a: 1 }, [{ op: "add", path: ["a"], after: 2 }]), ReplayInconsistent);
});

function snapshot(revision, transform = { position: [0, 0, 0], rotation: [0, 0, 0, 1], scale: 1 }) {
  const object = structuredClone(fixture.final_state.objects[fixture.final_state.order[0]]);
  object.transform = transform;
  return {
    session: { id: "spatial-0000000000000001", label: "t", revision, digest: "d", can_undo: true, can_redo: false, leases: [], pending_confirmations: [], presence_fresh: false, recovered_torn_tail: false },
    state: { ...fixture.final_state, objects: { [object.id]: object }, order: [object.id], selection: [] },
  };
}

test("scene store: previews overlay one object; stale snapshots are ignored", () => {
  const store = new SpatialSceneStore();
  const first = snapshot(3);
  const id = first.state.order[0];
  store.apply(first);
  store.setPreview(id, { position: [1, 0, 0], rotation: [0, 0, 0, 1], scale: 1 });
  assert.deepEqual(store.view().objects[id].transform.position, [1, 0, 0]);
  assert.deepEqual(store.current.state.objects[id].transform.position, [0, 0, 0], "authoritative state untouched");
  assert.equal(store.apply(snapshot(2)), false, "older revision ignored");
  store.apply(snapshot(4, { position: [2, 0, 0], rotation: [0, 0, 0, 1], scale: 1 }));
  assert.deepEqual(store.view().objects[id].transform.position, [1, 0, 0], "preview survives polling while held");
  store.clearPreview(id);
  assert.deepEqual(store.view().objects[id].transform.position, [2, 0, 0]);
  const v = store.view();
  assert.equal(store.view(), v, "view is memoised between changes");
});

function fakeApi({ refuseLease = false, failCommit = false } = {}) {
  const calls = [];
  let revision = 10;
  return {
    calls,
    api: {
      command: async (session, request, origin) => {
        calls.push(["command", request, origin]);
        if (failCommit) throw Object.assign(new Error("rejected"), { name: "ApiError" });
        revision += 1;
        return { status: "applied", snapshot: snapshot(revision, request.transform ?? undefined) };
      },
      beginLease: async (session, objectId) => {
        calls.push(["beginLease", objectId]);
        if (refuseLease) throw new Error("busy");
        return { id: "lease-1", object_id: objectId, origin: "gesture", expires_in: 4 };
      },
      renewLease: async () => calls.push(["renew"]),
      endLease: async (session, lease) => { calls.push(["endLease", lease]); return { ended: true }; },
      presence: async (session, anchors) => { calls.push(["presence", anchors]); return {}; },
    },
  };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

test("controller: one gesture manipulation → one lease → one gesture-origin commit with provenance", async () => {
  const { api, calls } = fakeApi();
  const store = new SpatialSceneStore();
  store.apply(snapshot(10));
  const id = store.current.state.order[0];
  const refused = [];
  const controller = new SpatialGestureController({ api, store, sessionId: () => "spatial-0000000000000001", provider: () => "synthetic", onError: () => {}, onRefused: (r) => refused.push(r), every: () => () => {} });
  const t = { position: [0, 0, 0], rotation: [0, 0, 0, 1], scale: 1 };
  controller.handle([{ type: "manipulation.begin", objectId: id, hand: 1, transform: t, at: 0 }]);
  for (let i = 1; i <= 5; i += 1) controller.handle([{ type: "manipulation.update", objectId: id, transform: { ...t, position: [i * 0.1, 0, 0] }, mode: "one_hand", at: i }]);
  assert.deepEqual(store.view().objects[id].transform.position, [0.5, 0, 0]);
  controller.handle([{ type: "manipulation.end", objectId: id, transform: { ...t, position: [0.5, 0, 0] }, reason: "release", at: 6,
    provenance: { gesture: "one_hand_move", duration_ms: 600, frames: 18, hands: [{ track: 1, handedness: "Right" }], mean_confidence: 0.9, tracking_losses: 0, spikes_absorbed: 0, glitches_rejected: 0 } }]);
  await settle(); await settle(); await settle();
  assert.deepEqual(calls.map((c) => c[0]), ["beginLease", "command"]);
  const [, request, origin] = calls[1];
  assert.equal(request.lease_id, "lease-1");
  assert.equal(origin.kind, "gesture");
  assert.equal(origin.input.gesture, "one_hand_move");
  assert.equal(origin.input.ended_by, "release");
  assert.equal(store.hasPreview(id), false);
  assert.deepEqual(store.view().objects[id].transform.position, [0.5, 0, 0]);
  assert.deepEqual(refused, []);
});

test("controller: refused lease or rejected commit snaps back to server state", async () => {
  const refusedApi = fakeApi({ refuseLease: true });
  const store = new SpatialSceneStore();
  store.apply(snapshot(10));
  const id = store.current.state.order[0];
  const refused = [];
  const controller = new SpatialGestureController({ api: refusedApi.api, store, sessionId: () => "s", provider: () => "synthetic", onError: () => {}, onRefused: (r) => refused.push(r), every: () => () => {} });
  controller.handle([{ type: "manipulation.begin", objectId: id, hand: 1, transform: { position: [0, 0, 0], rotation: [0, 0, 0, 1], scale: 1 }, at: 0 }]);
  controller.handle([{ type: "manipulation.update", objectId: id, transform: { position: [1, 0, 0], rotation: [0, 0, 0, 1], scale: 1 }, mode: "one_hand", at: 1 }]);
  await settle(); await settle();
  assert.equal(refused.length, 1);
  assert.equal(store.hasPreview(id), false);
  assert.deepEqual(store.view().objects[id].transform.position, [0, 0, 0]);

  const failing = fakeApi({ failCommit: true });
  const store2 = new SpatialSceneStore();
  store2.apply(snapshot(10));
  const errors = [];
  const controller2 = new SpatialGestureController({ api: failing.api, store: store2, sessionId: () => "s", provider: () => "synthetic", onError: (e) => errors.push(e), onRefused: () => {}, every: () => () => {} });
  controller2.handle([{ type: "manipulation.begin", objectId: id, hand: 1, transform: { position: [0, 0, 0], rotation: [0, 0, 0, 1], scale: 1 }, at: 0 }]);
  controller2.handle([{ type: "manipulation.end", objectId: id, transform: { position: [1, 0, 0], rotation: [0, 0, 0, 1], scale: 1 }, reason: "release", at: 1, provenance: {} }]);
  await settle(); await settle(); await settle();
  assert.equal(errors.length, 1);
  assert.equal(store2.hasPreview(id), false);
  assert.deepEqual(store2.view().objects[id].transform.position, [0, 0, 0]);
});

test("controller publishes throttled hand anchors on the interaction plane", () => {
  const { api, calls } = fakeApi();
  let now = 0;
  const controller = new SpatialGestureController({ api, store: new SpatialSceneStore(), sessionId: () => "s", provider: () => "synthetic", onError: () => {}, onRefused: () => {}, now: () => now });
  const projector = new PerspectiveProjector(DEFAULT_RIG, 16 / 9);
  const hand = { id: 1, handedness: "Right", handednessConfidence: 1, state: "tracking", score: 0.9, features: { pointer: { x: 0.7, y: 0.5 } } };
  controller.presence([hand], projector);
  now = 100;
  controller.presence([hand], projector);
  now = 400;
  controller.presence([{ ...hand, features: { pointer: { x: 0.6, y: 0.5 } } }], projector);
  const sent = calls.filter((c) => c[0] === "presence");
  assert.equal(sent.length, 2);
  assert.ok(sent[0][1].right_hand.position[0] > 0, "user's right hand appears on the right of the mirrored view");
  assert.equal(sent[0][1].right_hand.position[2], 0);
});

test("recordings: round trip, deterministic replay, and corrupt data rejected", () => {
  const recorder = new HandRecorder(100);
  for (let i = 0; i < 30; i += 1) {
    recorder.push({ timestamp: 1000 + i * 33.3, width: 1280, height: 720, hands: [syntheticHand({ ...OPEN_RIGHT, pinch: i > 10 ? 1 : 0 })], source: "live" });
  }
  const recording = recorder.export({ provider: "mediapipe-hands", kind: "live", device: "Test Cam" });
  const restored = validateRecording(JSON.parse(JSON.stringify(recording)));
  const frames = recordingFrames(restored, 5000);
  assert.equal(frames.length, 30);
  assert.equal(frames[0].timestamp, 5000);
  const run = () => {
    const pipeline = new GesturePipeline(gestureConfig(), new PerspectiveProjector(DEFAULT_RIG, 16 / 9), () => false, () => 0);
    const scene = { objects: [], selection: [], limits: { position_min: [-4, -1, -4], position_max: [4, 4, 2], scale_min: 0.1, scale_max: 10 } };
    return frames.map((f) => { const out = pipeline.process(f, scene, (p) => p); return out.poses.map((p) => `${p.pinch}`).join(); });
  };
  assert.deepEqual(run(), run(), "same recording → identical pose timeline");
  const corrupt = [
    { ...recording, schema: "other" },
    { ...recording, frames: [] },
    { ...recording, frames: [recording.frames[1], recording.frames[0]] },
    { ...recording, frames: [{ t: 0, hands: [{ handedness: "Right", handednessScore: 1, landmarks: [] }] }] },
    { ...recording, frames: [{ t: Number.NaN, hands: [] }] },
    { ...recording, source: { ...recording.source, resolution: { width: 0, height: 720 } } },
  ];
  for (const value of corrupt) assert.throws(() => validateRecording(value), RecordingInvalid);
  assert.equal(recording.schema, RECORDING_SCHEMA);
});
