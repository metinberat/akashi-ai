import type { Quat, Transform, Vec3 } from "./types.ts";

export type Point2 = { x: number; y: number };

export const IDENTITY_QUAT: Quat = [0, 0, 0, 1];

export const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
export const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
export const scaleVec = (a: Vec3, s: number): Vec3 => [a[0] * s, a[1] * s, a[2] * s];
export const length = (a: Vec3): number => Math.hypot(a[0], a[1], a[2]);
export const distance2 = (a: Point2, b: Point2): number => Math.hypot(a.x - b.x, a.y - b.y);
export const clamp = (value: number, min: number, max: number): number => Math.min(max, Math.max(min, value));

export function quatMultiply(a: Quat, b: Quat): Quat {
  const [ax, ay, az, aw] = a;
  const [bx, by, bz, bw] = b;
  return [
    aw * bx + ax * bw + ay * bz - az * by,
    aw * by - ax * bz + ay * bw + az * bx,
    aw * bz + ax * by - ay * bx + az * bw,
    aw * bw - ax * bx - ay * by - az * bz,
  ];
}

export function quatNormalize(q: Quat): Quat {
  const n = Math.hypot(q[0], q[1], q[2], q[3]);
  if (!Number.isFinite(n) || n < 1e-9) return [...IDENTITY_QUAT];
  let [x, y, z, w] = [q[0] / n, q[1] / n, q[2] / n, q[3] / n];
  // Same sign convention as backend/app/spatial/geometry.canonical_quat.
  for (const component of [w, x, y, z]) {
    if (Math.abs(component) > 1e-12) {
      if (component < 0) [x, y, z, w] = [-x, -y, -z, -w];
      break;
    }
  }
  return [x, y, z, w];
}

export function quatFromYaw(radians: number): Quat {
  return [0, Math.sin(radians / 2), 0, Math.cos(radians / 2)];
}

export function yawOf(q: Quat): number {
  const [x, y, z, w] = q;
  return Math.atan2(2 * (w * y + x * z), 1 - 2 * (y * y + x * x));
}

export function rotateWorldYaw(rotation: Quat, radians: number): Quat {
  return quatNormalize(quatMultiply(quatFromYaw(radians), rotation));
}

export function cloneTransform(transform: Transform): Transform {
  return { position: [...transform.position] as Vec3, rotation: [...transform.rotation] as Quat, scale: transform.scale };
}

export function transformsClose(a: Transform, b: Transform, epsilon = 1e-4): boolean {
  return a.position.every((v, i) => Math.abs(v - b.position[i]) < epsilon) &&
    a.rotation.every((v, i) => Math.abs(v - b.rotation[i]) < epsilon) &&
    Math.abs(a.scale - b.scale) < epsilon;
}

/** Round like the backend quantiser so committed values are stable. */
export function quantize(value: number, places = 6): number {
  const factor = 10 ** places;
  const rounded = Math.round(value * factor) / factor;
  return Object.is(rounded, -0) ? 0 : rounded;
}

export function quantizeTransform(transform: Transform): Transform {
  return {
    position: transform.position.map((v) => quantize(v)) as Vec3,
    rotation: quatNormalize(transform.rotation).map((v) => quantize(v)) as Quat,
    scale: quantize(transform.scale),
  };
}

export function clampTransform(transform: Transform, limits: { position_min: Vec3; position_max: Vec3; scale_min: number; scale_max: number }): Transform {
  return {
    position: transform.position.map((v, i) => clamp(v, limits.position_min[i], limits.position_max[i])) as Vec3,
    rotation: quatNormalize(transform.rotation),
    scale: clamp(transform.scale, limits.scale_min, limits.scale_max),
  };
}
