// Deterministic gesture-engine tests with synthetic hands. These validate the
// interaction logic (hysteresis, tracking loss, identity, two-hand math); they
// are NOT evidence of real webcam feel — see docs/acceptance/spatial-lab-v1.md.
import assert from "node:assert/strict";
import test from "node:test";

import { gestureConfig } from "../src/lib/spatial/gesture/config.ts";
import { computeFeatures } from "../src/lib/spatial/gesture/hand.ts";
import { OneEuroFilter } from "../src/lib/spatial/gesture/filters.ts";
import { GesturePipeline } from "../src/lib/spatial/gesture/pipeline.ts";
import { OPEN_RIGHT, jitter, syntheticHand } from "../src/lib/spatial/gesture/synthetic.ts";
import { PerspectiveProjector, DEFAULT_RIG } from "../src/lib/spatial/projection.ts";
import { imageToViewport, viewportToImage, DEFAULT_CALIBRATION } from "../src/lib/spatial/calibration.ts";
import { yawOf } from "../src/lib/spatial/math.ts";

const ASPECT = 16 / 9;
const LIMITS = { position_min: [-4, -1, -4], position_max: [4, 4, 2], scale_min: 0.1, scale_max: 10 };
const identity = (p) => ({ x: p.x, y: p.y });
const FRAME_MS = 1000 / 30;

function harness(overrides = {}) {
  const projector = new PerspectiveProjector(DEFAULT_RIG, ASPECT);
  const pipeline = new GesturePipeline(gestureConfig(overrides), projector, () => false, () => 0);
  const object = { id: "obj-000000000001", transform: { position: [0, 0, 0], rotation: [0, 0, 0, 1], scale: 1 }, size: [0.5, 1.7, 0.3], visible: true };
  const scene = { objects: [object], selection: [], limits: LIMITS };
  // Where the object's chest appears on screen: aim the synthetic pointer there.
  const chest = projector.project([0, 1.0, 0]);
  let now = 0;
  const intents = [];
  const step = (hands, frames = 1) => {
    let output;
    for (let i = 0; i < frames; i += 1) {
      now += FRAME_MS;
      output = pipeline.process({ timestamp: now, width: 1280, height: 720, hands, source: "synthetic" }, scene, identity);
      intents.push(...output.intents);
      for (const intent of output.intents) {
        if (intent.type === "manipulation.end") scene.objects[0].transform = intent.transform;
        if (intent.type === "select") scene.selection = [intent.objectId];
      }
    }
    return output;
  };
  // Synthetic pointer = thumb/index midpoint; palm sits slightly below it. Offset the palm so the pointer lands on target.
  const handAt = (pointer, extra = {}) => {
    const probe = syntheticHand({ ...OPEN_RIGHT, ...extra, center: { x: 0.5, y: 0.5 } }, ASPECT);
    const f = computeFeatures(probe, ASPECT, identity);
    return syntheticHand({ ...OPEN_RIGHT, ...extra, center: { x: pointer.x + (0.5 - f.pointer.x), y: pointer.y + (0.5 - f.pointer.y) } }, ASPECT, extra.noise);
  };
  return { pipeline, projector, scene, chest, step, handAt, intents, get now() { return now; } };
}

const types = (intents) => intents.filter((i) => i.type !== "hover").map((i) => i.type);

test("features are scale invariant: pinch ratio does not depend on hand size or distance", () => {
  for (const size of [0.08, 0.16, 0.3]) {
    const open = computeFeatures(syntheticHand({ ...OPEN_RIGHT, size }, ASPECT), ASPECT, identity);
    const pinched = computeFeatures(syntheticHand({ ...OPEN_RIGHT, size, pinch: 1 }, ASPECT), ASPECT, identity);
    const fist = computeFeatures(syntheticHand({ ...OPEN_RIGHT, size, curl: 1 }, ASPECT), ASPECT, identity);
    assert.ok(open.pinchRatio > 0.8, `open ${open.pinchRatio}`);
    assert.ok(pinched.pinchRatio < 0.1, `pinched ${pinched.pinchRatio}`);
    assert.ok(open.extension > 1.7 && fist.extension < 0.9, `${open.extension} ${fist.extension}`);
    assert.ok(pinched.indexExtension > 1.15, "a pinch keeps the index finger partly extended");
  }
});

test("one euro filter suppresses jitter at rest but follows fast motion", () => {
  const filter = new OneEuroFilter({ minCutoff: 1.5, beta: 6, dCutoff: 1 });
  const noise = jitter(7, 0.004);
  let maxRest = 0;
  for (let i = 0; i < 90; i += 1) maxRest = Math.max(maxRest, Math.abs(filter.filter(0.5 + noise(), i * FRAME_MS) - 0.5));
  assert.ok(maxRest < 0.006, `rest jitter ${maxRest}`);
  let value = 0;
  for (let i = 0; i < 15; i += 1) value = filter.filter(0.5 + (i + 1) * 0.03, (90 + i) * FRAME_MS);
  assert.ok(Math.abs(value - 0.95) < 0.08, `lag ${0.95 - value}`);
});

test("calibration mapping is invertible and honours mirroring and cover crop", () => {
  const image = { width: 1280, height: 720 };
  const viewport = { width: 1000, height: 1000 };
  const point = { x: 0.3, y: 0.6 };
  const v = imageToViewport(point, image, viewport, DEFAULT_CALIBRATION);
  assert.ok(v.x > 0.5, "mirrored: image-left hand appears on the right of the selfie view");
  const back = viewportToImage(v, image, viewport, DEFAULT_CALIBRATION);
  assert.ok(Math.abs(back.x - point.x) < 1e-9 && Math.abs(back.y - point.y) < 1e-9);
});

test("projector round trip: unproject then project returns the pointer", () => {
  const projector = new PerspectiveProjector(DEFAULT_RIG, ASPECT);
  const world = projector.toWorld({ x: 0.3, y: 0.4 }, 0);
  const screen = projector.project(world);
  assert.ok(Math.abs(screen.x - 0.3) < 1e-9 && Math.abs(screen.y - 0.4) < 1e-9);
});

test("quick pinch on an object selects it without moving it", () => {
  const h = harness();
  h.step([h.handAt(h.chest)], 8);
  h.step([h.handAt(h.chest, { pinch: 1 })], 4);
  h.step([h.handAt(h.chest)], 5);
  assert.deepEqual(types(h.intents), ["select"]);
  assert.deepEqual(h.scene.objects[0].transform.position, [0, 0, 0]);
});

test("pinch-drag moves the object with the hand and commits once on release", () => {
  const h = harness();
  h.step([h.handAt(h.chest)], 8);
  h.step([h.handAt(h.chest, { pinch: 1 })], 4); // pinch, then drag
  for (let i = 0; i <= 20; i += 1) h.step([h.handAt({ x: h.chest.x + i * 0.01, y: h.chest.y }, { pinch: 1 })]);
  h.step([h.handAt({ x: h.chest.x + 0.2, y: h.chest.y }, { pinch: 1 })], 8); // people settle before letting go
  h.step([h.handAt({ x: h.chest.x + 0.2, y: h.chest.y })], 6);
  const kinds = types(h.intents);
  assert.equal(kinds.filter((k) => k === "manipulation.begin").length, 1);
  assert.equal(kinds.filter((k) => k === "manipulation.end").length, 1);
  const end = h.intents.find((i) => i.type === "manipulation.end");
  assert.equal(end.reason, "release");
  assert.equal(end.provenance.gesture, "one_hand_move");
  const expected = h.projector.toWorld({ x: h.chest.x + 0.2, y: h.chest.y }, 0)[0] - h.projector.toWorld(h.chest, 0)[0];
  assert.ok(Math.abs(end.transform.position[0] - expected) < 0.03, `${end.transform.position[0]} vs ${expected}`);
  assert.equal(end.transform.position[2], 0, "2.5D: depth is not inferred");
});

test("jitter around the pinch threshold does not chatter (hysteresis + dwell)", () => {
  const h = harness();
  h.step([h.handAt(h.chest)], 8);
  // Pinch amount oscillating around the enter threshold every frame.
  for (let i = 0; i < 60; i += 1) h.step([h.handAt(h.chest, { pinch: i % 2 ? 0.66 : 0.72 })]);
  const starts = h.pipeline.poses;
  assert.ok(starts);
  const kinds = types(h.intents);
  assert.ok(kinds.filter((k) => k === "select").length <= 1, `chatter: ${kinds.join(",")}`);
  assert.equal(kinds.filter((k) => k.startsWith("manipulation")).length, 0);
});

test("a teleport-sized jump never drags the object; the re-detected hand continues relatively", () => {
  const h = harness();
  h.step([h.handAt(h.chest)], 8);
  h.step([h.handAt(h.chest, { pinch: 1 })], 4);
  for (let i = 0; i <= 16; i += 1) h.step([h.handAt({ x: h.chest.x + i * 0.005, y: h.chest.y }, { pinch: 1 })]);
  const before = h.intents.filter((i) => i.type === "manipulation.update").at(-1).transform.position[0];
  const far = { x: h.chest.x + 0.45, y: h.chest.y };
  h.step([h.handAt(far, { pinch: 1 })], 15);
  for (const update of h.intents.filter((i) => i.type === "manipulation.update")) {
    assert.ok(update.transform.position[0] <= before + 1e-9, "object never followed the jump");
  }
  h.step([h.handAt({ x: far.x + 0.05, y: far.y }, { pinch: 1 })], 10);
  h.step([h.handAt({ x: far.x + 0.05, y: far.y })], 6);
  const end = h.intents.find((i) => i.type === "manipulation.end");
  assert.equal(end.reason, "release");
  const step = h.projector.toWorld({ x: far.x + 0.05, y: far.y }, 0)[0] - h.projector.toWorld(far, 0)[0];
  assert.ok(Math.abs(end.transform.position[0] - (before + step)) < 0.04, `${end.transform.position[0]} vs ${before + step}`);
});

test("a one-frame detector glitch is rejected before smoothing", () => {
  const h = harness();
  h.step([h.handAt(h.chest)], 8);
  h.step([h.handAt(h.chest, { pinch: 1 })], 4);
  for (let i = 0; i <= 16; i += 1) h.step([h.handAt({ x: h.chest.x, y: h.chest.y - i * 0.005 }, { pinch: 1 })]);
  const path = { x: h.chest.x, y: h.chest.y - 0.08 };
  // Where the hand path really leads (object follows the pointer delta on its plane).
  const limit = h.projector.toWorld(path, 0)[1] - h.projector.toWorld(h.chest, 0)[1];
  h.step([h.handAt({ x: path.x, y: path.y - 0.15 }, { pinch: 1 })]); // single bad frame
  h.step([h.handAt(path, { pinch: 1 })], 6);
  for (const update of h.intents.filter((i) => i.type === "manipulation.update")) {
    assert.ok(update.transform.position[1] <= limit + 0.02, `object twitched to ${update.transform.position[1]} (path ${limit})`);
  }
  h.step([h.handAt(path)], 6);
  const end = h.intents.find((i) => i.type === "manipulation.end");
  assert.equal(end.reason, "release");
  assert.equal(end.provenance.glitches_rejected, 1);
});

test("brief occlusion is coasted; long loss ends at the last stable transform", () => {
  const h = harness({ graceMs: 300 });
  h.step([h.handAt(h.chest)], 8);
  for (let i = 0; i <= 10; i += 1) h.step([h.handAt({ x: h.chest.x + i * 0.01, y: h.chest.y }, { pinch: 1 })]);
  const stable = h.intents.filter((i) => i.type === "manipulation.update").at(-1).transform;
  h.step([], 4); // ~133 ms occlusion: coast
  assert.equal(h.intents.some((i) => i.type === "manipulation.end"), false);
  h.step([h.handAt({ x: h.chest.x + 0.12, y: h.chest.y }, { pinch: 1 })], 3);
  assert.equal(h.intents.some((i) => i.type === "manipulation.end"), false, "re-acquired within grace");
  const resumed = h.intents.filter((i) => i.type === "manipulation.update").at(-1).transform;
  h.step([], 15); // ~500 ms: lost
  const end = h.intents.find((i) => i.type === "manipulation.end");
  assert.equal(end.reason, "tracking_lost");
  assert.deepEqual(end.transform.position.map((v) => Math.round(v * 1e4)), resumed.position.map((v) => Math.round(v * 1e4)));
  assert.ok(end.provenance.tracking_losses >= 1);
  assert.notDeepEqual(resumed.position, stable.position);
});

test("handedness label flips do not swap hand identity", () => {
  const h = harness();
  const left = { x: 0.3, y: 0.5 };
  const right = { x: 0.7, y: 0.5 };
  h.step([h.handAt(left, { handedness: "Left" }), h.handAt(right)], 5);
  const ids = h.pipeline.tracker.update.length >= 0 && h.step([h.handAt(left, { handedness: "Left" }), h.handAt(right)]).hands.map((x) => [x.id, x.handedness]);
  // Provider swaps labels and order for a few frames (common when hands cross the midline).
  let out;
  for (let i = 0; i < 4; i += 1) out = h.step([h.handAt(right, { handedness: "Left" }), h.handAt(left, { handedness: "Right" })]);
  assert.deepEqual(out.hands.map((x) => [x.id, x.handedness]), ids, "ids and voted handedness stay with the physical hands");
});

test("two-hand pinch scales by hand distance and turns by twist, then commits once", () => {
  const h = harness();
  const object = h.scene.objects[0];
  const a = { x: h.chest.x - 0.02, y: h.chest.y };
  h.step([h.handAt(a)], 8);
  for (let i = 0; i < 14; i += 1) h.step([h.handAt(a, { pinch: 1 })]);
  const b0 = { x: a.x + 0.25, y: a.y };
  h.step([h.handAt(a, { pinch: 1 }), h.handAt(b0, { handedness: "Left" })], 8);
  for (let i = 1; i <= 25; i += 1) {
    const angle = (i / 25) * 0.4;
    const dist = 0.25 * (1 + (i / 25) * 0.5);
    h.step([h.handAt(a, { pinch: 1 }), h.handAt({ x: a.x + Math.cos(angle) * dist, y: a.y - Math.sin(angle) * dist }, { handedness: "Left", pinch: 1 })]);
  }
  const finalB = { x: a.x + Math.cos(0.4) * 0.375, y: a.y - Math.sin(0.4) * 0.375 };
  h.step([h.handAt(a, { pinch: 1 }), h.handAt(finalB, { handedness: "Left", pinch: 1 })], 8);
  h.step([h.handAt(a), h.handAt(finalB, { handedness: "Left" })], 8);
  const end = h.intents.find((i) => i.type === "manipulation.end");
  assert.equal(end.reason, "release");
  assert.notEqual(end.provenance.gesture, "one_hand_move");
  assert.ok(end.transform.scale > 1.3 && end.transform.scale < 1.7, `scale ${end.transform.scale}`);
  assert.ok(Math.abs(yawOf(end.transform.rotation)) > 0.2, `yaw ${yawOf(end.transform.rotation)}`);
  assert.equal(types(h.intents).filter((k) => k === "manipulation.end").length, 1);
  assert.equal(object.transform.scale, end.transform.scale);
});

test("pinching empty space does nothing; newly acquired hands must settle", () => {
  const h = harness();
  h.step([h.handAt({ x: 0.05, y: 0.1 }, { pinch: 1 })], 20);
  h.step([h.handAt({ x: 0.05, y: 0.1 })], 5);
  assert.deepEqual(types(h.intents), []);
  const fresh = harness();
  fresh.step([fresh.handAt(fresh.chest, { pinch: 1 })], 2); // pinching from the first frame
  fresh.step([fresh.handAt(fresh.chest)], 5);
  assert.deepEqual(types(fresh.intents), [], "entry noise is not a tap");
});

test("closing a fist grabs; fist and pinch never both activate", () => {
  const h = harness();
  h.step([h.handAt(h.chest)], 8);
  for (let i = 0; i <= 20; i += 1) {
    const out = h.step([h.handAt({ x: h.chest.x, y: h.chest.y - i * 0.006 }, { curl: 1 })]);
    for (const pose of out.poses) assert.ok(!(pose.pinch && pose.grab));
  }
  h.step([h.handAt({ x: h.chest.x, y: h.chest.y - 0.12 })], 6);
  const end = h.intents.find((i) => i.type === "manipulation.end");
  assert.ok(end, "grab-drag commits a move");
  assert.ok(end.transform.position[1] > 0.05);
});

test("noisy synthetic tracking (σ=0.003) still yields exactly one clean drag", () => {
  const h = harness();
  const noise = jitter(42, 0.003);
  h.step([h.handAt(h.chest, { noise })], 10);
  for (let i = 0; i <= 25; i += 1) h.step([h.handAt({ x: h.chest.x + i * 0.008, y: h.chest.y }, { pinch: 1, noise })]);
  h.step([h.handAt({ x: h.chest.x + 0.2, y: h.chest.y }, { noise })], 10);
  const kinds = types(h.intents);
  assert.equal(kinds.filter((k) => k === "manipulation.begin").length, 1, kinds.join(","));
  assert.equal(kinds.filter((k) => k === "manipulation.end").length, 1, kinds.join(","));
});

test("pipeline measures frame rate and gaps from timestamps", () => {
  const h = harness();
  const out = h.step([h.handAt(h.chest)], 30);
  assert.ok(Math.abs(out.metrics.fps - 30) < 1, `fps ${out.metrics.fps}`);
  assert.equal(out.metrics.gaps, 0);
});
