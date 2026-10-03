// Parametric synthetic hand (MediaPipe 21-point layout) for deterministic tests
// and the in-app "simulated hands" input. SYNTHETIC: geometry is a plausible
// schematic hand, not a model of real hand appearance or real tracker noise.

import type { HandObservation, Handedness, Point3 } from "./hand.ts";

export type SyntheticHandPose = {
  /** Palm centre in normalised image coordinates. */
  center: { x: number; y: number };
  /** Wrist→middle-MCP length as a fraction of image height. */
  size: number;
  /** In-plane rotation (radians). */
  roll: number;
  /** 0 = thumb and index apart, 1 = touching. */
  pinch: number;
  /** 0 = fingers extended, 1 = fist. */
  curl: number;
  handedness: Handedness;
  score: number;
};

type P2 = [number, number];
// Right hand, palm towards camera, fingers up (image y grows downward). Units: hand length.
const TEMPLATE: P2[] = [
  [0, 0],
  [-0.35, -0.25], [-0.6, -0.5], [-0.8, -0.75], [-0.95, -1.0],
  [-0.32, -0.95], [-0.36, -1.35], [-0.38, -1.6], [-0.4, -1.82],
  [0, -1], [0, -1.45], [0, -1.72], [0, -1.95],
  [0.28, -0.95], [0.3, -1.35], [0.31, -1.58], [0.32, -1.78],
  [0.52, -0.85], [0.58, -1.15], [0.62, -1.35], [0.65, -1.52],
];
const PALM: P2 = [0.096, -0.75];
const FINGER_CHAINS = [[5, 6, 7, 8], [9, 10, 11, 12], [13, 14, 15, 16], [17, 18, 19, 20]];
const lerp = (a: P2, b: P2, t: number): P2 => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];

export function syntheticHand(pose: SyntheticHandPose, aspect = 16 / 9, noise?: () => number): HandObservation {
  const points = TEMPLATE.map((p) => [...p] as P2);
  const curl = Math.min(Math.max(pose.curl, 0), 1);
  for (const [mcp, pip, dip, tip] of FINGER_CHAINS) {
    const base = TEMPLATE[mcp];
    points[pip] = lerp(TEMPLATE[pip], [base[0], base[1] - 0.25], curl);
    points[dip] = lerp(TEMPLATE[dip], [base[0], base[1] + 0.05], curl);
    points[tip] = lerp(TEMPLATE[tip], [base[0], base[1] + 0.35], curl);
  }
  const pinch = Math.min(Math.max(pose.pinch, 0), 1);
  if (pinch > 0) {
    const meet: P2 = [-0.62, -1.2];
    points[4] = lerp(points[4], [meet[0] - 0.03, meet[1]], pinch);
    points[3] = lerp(points[3], [-0.72, -0.98], pinch);
    points[8] = lerp(points[8], [meet[0] + 0.03, meet[1]], pinch);
    points[7] = lerp(points[7], [-0.52, -1.38], pinch);
  }
  const mirror = pose.handedness === "Left" ? -1 : 1;
  const cos = Math.cos(pose.roll);
  const sin = Math.sin(pose.roll);
  const z = (i: number) => (FINGER_CHAINS.some((chain) => chain.slice(1).includes(i)) ? -0.25 * curl : 0);
  const landmarks: Point3[] = points.map((p, i) => {
    const dx = (p[0] - PALM[0]) * mirror * pose.size;
    const dy = (p[1] - PALM[1]) * pose.size;
    const rx = dx * cos - dy * sin;
    const ry = dx * sin + dy * cos;
    return { x: pose.center.x + rx / aspect + (noise ? noise() : 0), y: pose.center.y + ry + (noise ? noise() : 0), z: z(i) * pose.size };
  });
  const worldLandmarks: Point3[] = points.map((p, i) => ({ x: (p[0] - PALM[0]) * mirror * 0.085, y: (p[1] - PALM[1]) * 0.085, z: z(i) * 0.085 }));
  return { handedness: pose.handedness, handednessScore: pose.score, landmarks, worldLandmarks };
}

/** Small deterministic PRNG (mulberry32) for reproducible jitter. */
export function seededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Approximately Gaussian jitter (sum of uniforms) with standard deviation sigma. */
export function jitter(seed: number, sigma: number): () => number {
  const random = seededRandom(seed);
  return () => ((random() + random() + random() + random() - 2) / Math.sqrt(1 / 3)) * sigma;
}

export const OPEN_RIGHT: SyntheticHandPose = { center: { x: 0.5, y: 0.5 }, size: 0.16, roll: 0, pinch: 0, curl: 0, handedness: "Right", score: 0.95 };
