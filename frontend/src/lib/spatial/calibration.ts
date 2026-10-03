// Camera image → viewport mapping. The camera feed is drawn behind the scene
// with CSS object-fit; this mapping reproduces exactly the same crop so a hand
// cursor sits over the hand the user sees. gain/offset let local calibration
// widen the reachable area. All values here are LOCAL ACCEPTANCE tunables.

import type { Point2 } from "./math.ts";

export type CameraCalibration = {
  /** Selfie view: the feed is shown mirrored, so image x is flipped. */
  mirror: boolean;
  fit: "cover" | "contain";
  /** MediaPipe labels handedness assuming a mirrored image; raw webcam frames need a swap. */
  swapHandedness: boolean;
  /** Scales pointer motion around the viewport centre (1 = exact overlay). */
  gain: number;
  offset: Point2;
};

export const DEFAULT_CALIBRATION: CameraCalibration = { mirror: true, fit: "cover", swapHandedness: true, gain: 1, offset: { x: 0, y: 0 } };

export type Size = { width: number; height: number };

export function imageToViewport(point: Point2, image: Size, viewport: Size, calibration: CameraCalibration): Point2 {
  const x = calibration.mirror ? 1 - point.x : point.x;
  let vx = x;
  let vy = point.y;
  if (image.width > 0 && image.height > 0 && viewport.width > 0 && viewport.height > 0) {
    const scale = calibration.fit === "cover"
      ? Math.max(viewport.width / image.width, viewport.height / image.height)
      : Math.min(viewport.width / image.width, viewport.height / image.height);
    const drawnWidth = image.width * scale;
    const drawnHeight = image.height * scale;
    vx = ((viewport.width - drawnWidth) / 2 + x * drawnWidth) / viewport.width;
    vy = ((viewport.height - drawnHeight) / 2 + point.y * drawnHeight) / viewport.height;
  }
  return {
    x: 0.5 + (vx - 0.5) * calibration.gain + calibration.offset.x,
    y: 0.5 + (vy - 0.5) * calibration.gain + calibration.offset.y,
  };
}

export function viewportToImage(point: Point2, image: Size, viewport: Size, calibration: CameraCalibration): Point2 {
  const vx = 0.5 + (point.x - calibration.offset.x - 0.5) / calibration.gain;
  const vy = 0.5 + (point.y - calibration.offset.y - 0.5) / calibration.gain;
  const scale = calibration.fit === "cover"
    ? Math.max(viewport.width / image.width, viewport.height / image.height)
    : Math.min(viewport.width / image.width, viewport.height / image.height);
  const drawnWidth = image.width * scale;
  const drawnHeight = image.height * scale;
  const x = (vx * viewport.width - (viewport.width - drawnWidth) / 2) / drawnWidth;
  const y = (vy * viewport.height - (viewport.height - drawnHeight) / 2) / drawnHeight;
  return { x: calibration.mirror ? 1 - x : x, y };
}
