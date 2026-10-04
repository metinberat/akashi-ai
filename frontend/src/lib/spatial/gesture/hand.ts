// Hand landmark model (MediaPipe 21-point topology) and scale-invariant features.

import type { Point2 } from "../math.ts";

export const L = {
  WRIST: 0, THUMB_CMC: 1, THUMB_MCP: 2, THUMB_IP: 3, THUMB_TIP: 4,
  INDEX_MCP: 5, INDEX_PIP: 6, INDEX_DIP: 7, INDEX_TIP: 8,
  MIDDLE_MCP: 9, MIDDLE_PIP: 10, MIDDLE_DIP: 11, MIDDLE_TIP: 12,
  RING_MCP: 13, RING_PIP: 14, RING_DIP: 15, RING_TIP: 16,
  PINKY_MCP: 17, PINKY_PIP: 18, PINKY_DIP: 19, PINKY_TIP: 20,
} as const;

export const FINGERS = [
  { mcp: L.INDEX_MCP, tip: L.INDEX_TIP },
  { mcp: L.MIDDLE_MCP, tip: L.MIDDLE_TIP },
  { mcp: L.RING_MCP, tip: L.RING_TIP },
  { mcp: L.PINKY_MCP, tip: L.PINKY_TIP },
] as const;

export type Point3 = { x: number; y: number; z: number };
export type Handedness = "Left" | "Right";

/** One detected hand as reported by an input provider (raw, unsmoothed). */
export type HandObservation = {
  handedness: Handedness;
  handednessScore: number;
  /** 21 points, normalised image coordinates: x right, y down, in [0, 1]. */
  landmarks: Point3[];
  /** Optional 21 points in metres around the hand centre (MediaPipe world landmarks). */
  worldLandmarks?: Point3[];
};

export type ProviderKind = "live" | "recorded" | "synthetic";

export type HandFrame = {
  /** Monotonic timestamp in milliseconds of when the frame was captured/produced. */
  timestamp: number;
  /** Source image size in pixels (aspect ratio matters for distances). */
  width: number;
  height: number;
  hands: HandObservation[];
  source: ProviderKind;
  frameId?: number;
  /** Optional provider-measured inference time in milliseconds. */
  inferenceMs?: number;
};

export type HandFeatures = {
  /** Palm centre in viewport coordinates [0, 1]. */
  palm: Point2;
  /** Interaction pointer (thumb/index midpoint) in viewport coordinates. */
  pointer: Point2;
  /** Hand size (wrist → middle MCP) in viewport units; used to scale motion thresholds. */
  scale: number;
  /** Thumb-tip to index-tip distance divided by hand length. ~1 open, <0.3 pinched. */
  pinchRatio: number;
  /** Mean fingertip/MCP distance ratio from the wrist for index..pinky. ~1.9 open, <1.2 fist. */
  extension: number;
  /** Index finger extension ratio alone (a pinch keeps the index finger partly extended). */
  indexExtension: number;
  /** Largest extension among index..pinky: a grab needs every finger curled (pointing is not a grab). */
  maxExtension: number;
  /** Knuckle-line angle in the image plane (radians). */
  roll: number;
};

export function validObservation(value: unknown): value is HandObservation {
  if (!value || typeof value !== "object") return false;
  const hand = value as HandObservation;
  const finitePoint = (p: Point3) => p && Number.isFinite(p.x) && Number.isFinite(p.y) && Number.isFinite(p.z ?? 0);
  return (hand.handedness === "Left" || hand.handedness === "Right") && Number.isFinite(hand.handednessScore) &&
    Array.isArray(hand.landmarks) && hand.landmarks.length === 21 && hand.landmarks.every(finitePoint) &&
    (hand.worldLandmarks === undefined || (Array.isArray(hand.worldLandmarks) && hand.worldLandmarks.length === 21 && hand.worldLandmarks.every(finitePoint)));
}

const d3 = (a: Point3, b: Point3) => Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);

/** Image-space distance with aspect correction (units of image height). */
function dImage(a: Point3, b: Point3, aspect: number) {
  return Math.hypot((a.x - b.x) * aspect, a.y - b.y);
}

export function palmCenter(points: Point3[]): Point2 {
  const ids: number[] = [L.WRIST, L.INDEX_MCP, L.MIDDLE_MCP, L.RING_MCP, L.PINKY_MCP];
  return { x: ids.reduce((s, i) => s + points[i].x, 0) / ids.length, y: ids.reduce((s, i) => s + points[i].y, 0) / ids.length };
}

export type ImageToViewport = (point: Point2) => Point2;

export function computeFeatures(hand: HandObservation, aspect: number, toViewport: ImageToViewport): HandFeatures {
  const p = hand.landmarks;
  const world = hand.worldLandmarks;
  const dist = world ? (a: number, b: number) => d3(world[a], world[b]) : (a: number, b: number) => dImage(p[a], p[b], aspect);
  const length = Math.max(dist(L.WRIST, L.MIDDLE_MCP), 1e-6);
  const pinchRatio = dist(L.THUMB_TIP, L.INDEX_TIP) / length;
  const ratios = FINGERS.map((f) => dist(L.WRIST, f.tip) / Math.max(dist(L.WRIST, f.mcp), 1e-6));
  const extension = ratios.reduce((s, r) => s + r, 0) / ratios.length;
  const palmImage = palmCenter(p);
  const pointerImage = { x: (p[L.THUMB_TIP].x + p[L.INDEX_TIP].x) / 2, y: (p[L.THUMB_TIP].y + p[L.INDEX_TIP].y) / 2 };
  const palm = toViewport(palmImage);
  const pointer = toViewport(pointerImage);
  const wristV = toViewport({ x: p[L.WRIST].x, y: p[L.WRIST].y });
  const middleV = toViewport({ x: p[L.MIDDLE_MCP].x, y: p[L.MIDDLE_MCP].y });
  return {
    palm,
    pointer,
    scale: Math.max(Math.hypot(middleV.x - wristV.x, middleV.y - wristV.y), 1e-4),
    pinchRatio,
    extension,
    indexExtension: ratios[0],
    maxExtension: Math.max(...ratios),
    roll: Math.atan2(p[L.PINKY_MCP].y - p[L.INDEX_MCP].y, (p[L.PINKY_MCP].x - p[L.INDEX_MCP].x) * aspect),
  };
}
