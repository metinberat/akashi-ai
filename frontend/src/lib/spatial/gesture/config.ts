// Gesture tunables. Defaults are reasoned starting points validated only against
// synthetic hands and still photographs in the cloud. Every value marked
// LOCAL ACCEPTANCE REQUIRED must be tuned on the physical webcam
// (docs/acceptance/spatial-lab-v1.md, section "Gesture feel").

import type { OneEuroParams } from "./filters.ts";

export type HysteresisConfig = { enter: number; exit: number; enterDwellMs: number; exitDwellMs: number; cooldownMs: number };

export type GestureConfig = {
  maxHands: number;
  /** Below this provider handedness/presence score a hand is "degraded": no new pose transitions. */
  minScore: number;
  imageFilter: OneEuroParams;
  worldFilter: OneEuroParams;
  /** Max palm movement (image-height units) for associating a detection with an existing track. */
  matchDistance: number;
  /** Raw palm jumps above this (but inside matchDistance) are held for one frame and only accepted if the next frame confirms them. */
  outlierJump: number;
  /** Keep a track alive through brief occlusion/missed detections (ms). */
  graceMs: number;
  /** Newly acquired hands cannot start a pose until settled (ms) — suppresses entry noise. */
  settleMs: number;
  pinch: HysteresisConfig & { minIndexExtension: number };
  grab: HysteresisConfig;
  tap: { maxMs: number; maxMove: number };
  drag: { startMove: number; holdMs: number };
  pickMargin: number;
  /** Pointer jump (viewport units) within one frame treated as a tracking glitch during manipulation. */
  spikeMove: number;
  twoHand: { scaleDeadband: number; rotateDeadband: number; rotationSign: 1 | -1 };
  updateEpsilon: number;
};

export const DEFAULT_GESTURE_CONFIG: GestureConfig = {
  maxHands: 2,
  minScore: 0.5,
  imageFilter: { minCutoff: 1.5, beta: 6, dCutoff: 1 }, // LOCAL ACCEPTANCE REQUIRED
  worldFilter: { minCutoff: 2, beta: 20, dCutoff: 1 }, // LOCAL ACCEPTANCE REQUIRED
  matchDistance: 0.22,
  outlierJump: 0.1, // LOCAL ACCEPTANCE REQUIRED (fast swipes vs. detector glitches)
  graceMs: 300, // LOCAL ACCEPTANCE REQUIRED (occlusion vs. responsiveness)
  settleMs: 120,
  pinch: { enter: 0.32, exit: 0.48, enterDwellMs: 50, exitDwellMs: 90, cooldownMs: 180, minIndexExtension: 1.15 }, // LOCAL ACCEPTANCE REQUIRED
  grab: { enter: 1.22, exit: 1.45, enterDwellMs: 90, exitDwellMs: 120, cooldownMs: 200 }, // LOCAL ACCEPTANCE REQUIRED
  tap: { maxMs: 320, maxMove: 0.35 },
  drag: { startMove: 0.25, holdMs: 380 },
  pickMargin: 0.02,
  spikeMove: 0.18,
  twoHand: { scaleDeadband: 0.015, rotateDeadband: 0.02, rotationSign: -1 },
  updateEpsilon: 0.0005,
};

export function gestureConfig(overrides: Partial<GestureConfig> = {}): GestureConfig {
  return {
    ...DEFAULT_GESTURE_CONFIG,
    ...overrides,
    pinch: { ...DEFAULT_GESTURE_CONFIG.pinch, ...overrides.pinch },
    grab: { ...DEFAULT_GESTURE_CONFIG.grab, ...overrides.grab },
    tap: { ...DEFAULT_GESTURE_CONFIG.tap, ...overrides.tap },
    drag: { ...DEFAULT_GESTURE_CONFIG.drag, ...overrides.drag },
    twoHand: { ...DEFAULT_GESTURE_CONFIG.twoHand, ...overrides.twoHand },
  };
}
