// Deterministic regression on REAL MediaPipe landmarks (still photographs via
// Chromium's fake camera; see tests/fixtures/spatial/real-landmarks/README.md).
// Real model output, but not live motion: pinch on real hands is still
// LOCAL ACCEPTANCE REQUIRED because none of these photos shows a pinch.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { gestureConfig } from "../src/lib/spatial/gesture/config.ts";
import { computeFeatures } from "../src/lib/spatial/gesture/hand.ts";
import { GesturePipeline } from "../src/lib/spatial/gesture/pipeline.ts";
import { DEFAULT_RIG, PerspectiveProjector } from "../src/lib/spatial/projection.ts";
import { recordingFrames, validateRecording } from "../src/lib/spatial/providers/recorded.ts";

const load = (name) => validateRecording(JSON.parse(readFileSync(new URL(`./fixtures/spatial/real-landmarks/${name}.json`, import.meta.url))));
const LIMITS = { position_min: [-4, -1, -4], position_max: [4, 4, 2], scale_min: 0.1, scale_max: 10 };

function run(recording) {
  const aspect = recording.source.resolution.width / recording.source.resolution.height;
  const pipeline = new GesturePipeline(gestureConfig(), new PerspectiveProjector(DEFAULT_RIG, aspect), () => false, () => 0);
  const seen = { pinch: false, grab: false, maxTracks: 0, tracks: new Set() };
  for (const frame of recordingFrames(recording)) {
    const out = pipeline.process(frame, { objects: [], selection: [], limits: LIMITS }, (p) => p);
    seen.pinch ||= out.poses.some((p) => p.pinch);
    seen.grab ||= out.poses.some((p) => p.grab);
    seen.maxTracks = Math.max(seen.maxTracks, out.hands.length);
    for (const hand of out.hands) seen.tracks.add(hand.id);
  }
  return seen;
}

const expectations = {
  fist: { grab: true, hands: 1 },
  thumb_up: { grab: true, hands: 1 },
  pointing_up: { grab: false, hands: 1 },
  victory: { grab: false, hands: 1 },
  right_hands: { grab: false, hands: 2 },
  left_hands: { grab: false, hands: 2 },
};

for (const [name, expected] of Object.entries(expectations)) {
  test(`real landmarks: ${name}`, () => {
    const recording = load(name);
    const result = run(recording);
    assert.equal(result.pinch, false, "no photo shows a pinch");
    assert.equal(result.grab, expected.grab, `grab for ${name}`);
    assert.equal(result.maxTracks, expected.hands);
    assert.equal(result.tracks.size, expected.hands, "stable identities: no re-acquisitions on a still image");
  });
}

test("real landmarks separate pointing from a fist only when every finger must curl", () => {
  const feature = (name) => {
    const recording = load(name);
    const aspect = recording.source.resolution.width / recording.source.resolution.height;
    return computeFeatures(recording.frames[0].hands[0], aspect, (p) => p);
  };
  const fist = feature("fist");
  const pointing = feature("pointing_up");
  const config = gestureConfig();
  assert.ok(fist.maxExtension < config.grab.enter, `fist max ${fist.maxExtension}`);
  assert.ok(pointing.maxExtension > config.grab.exit, `pointing max ${pointing.maxExtension}`);
  // The mean alone would not separate them: three curled fingers dominate a pointing hand.
  assert.ok(pointing.extension < config.grab.exit, `pointing mean ${pointing.extension}`);
  // A fist brings thumb and index close: the index-extension guard is what prevents a false pinch.
  assert.ok(fist.indexExtension < config.pinch.minIndexExtension);
});
