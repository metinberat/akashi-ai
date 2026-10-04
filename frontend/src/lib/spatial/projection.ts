// One camera definition shared by the three.js renderer and gesture hit-testing,
// so what the user points at is exactly what is drawn there.

import type { Vec3 } from "./types.ts";
import type { Point2 } from "./math.ts";
import type { InteractionObject, SceneProjector } from "./gesture/interaction.ts";

export type CameraRig = { fov: number; position: Vec3; target: Vec3; near: number; far: number };

export const DEFAULT_RIG: CameraRig = { fov: 50, position: [0, 1.15, 4.2], target: [0, 0.9, 0], near: 0.01, far: 100 };

const normalize = (v: Vec3): Vec3 => {
  const n = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / n, v[1] / n, v[2] / n];
};
const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

export class PerspectiveProjector implements SceneProjector {
  private forward: Vec3;
  private right: Vec3;
  private up: Vec3;
  private tanHalf: number;

  constructor(readonly rig: CameraRig, public aspect: number) {
    this.setAspect(aspect);
    this.forward = normalize([rig.target[0] - rig.position[0], rig.target[1] - rig.position[1], rig.target[2] - rig.position[2]]);
    this.right = normalize(cross(this.forward, [0, 1, 0]));
    this.up = cross(this.right, this.forward);
    this.tanHalf = Math.tan((rig.fov * Math.PI) / 360);
  }

  setAspect(aspect: number): void {
    if (Number.isFinite(aspect) && aspect > 0) this.aspect = aspect;
  }

  /** World point → viewport coordinates ([0,1], y down) and view depth. */
  project(point: Vec3): { x: number; y: number; depth: number } | null {
    const d: Vec3 = [point[0] - this.rig.position[0], point[1] - this.rig.position[1], point[2] - this.rig.position[2]];
    const depth = dot(d, this.forward);
    if (depth <= this.rig.near) return null;
    const x = dot(d, this.right) / (depth * this.tanHalf * this.aspect);
    const y = dot(d, this.up) / (depth * this.tanHalf);
    return { x: (x + 1) / 2, y: (1 - y) / 2, depth };
  }

  /** Viewport point → intersection of the view ray with the plane z = planeZ. */
  toWorld(pointer: Point2, planeZ: number): Vec3 | null {
    const nx = pointer.x * 2 - 1;
    const ny = 1 - pointer.y * 2;
    const direction = normalize([
      this.forward[0] + this.right[0] * nx * this.tanHalf * this.aspect + this.up[0] * ny * this.tanHalf,
      this.forward[1] + this.right[1] * nx * this.tanHalf * this.aspect + this.up[1] * ny * this.tanHalf,
      this.forward[2] + this.right[2] * nx * this.tanHalf * this.aspect + this.up[2] * ny * this.tanHalf,
    ]);
    if (Math.abs(direction[2]) < 1e-6) return null;
    const t = (planeZ - this.rig.position[2]) / direction[2];
    if (t <= 0) return null;
    return [this.rig.position[0] + direction[0] * t, this.rig.position[1] + direction[1] * t, planeZ];
  }

  /** Screen rectangle of an object's upright bounding box. */
  screenRect(object: InteractionObject): { x0: number; y0: number; x1: number; y1: number; depth: number } | null {
    const [x, y, z] = object.transform.position;
    const scale = object.transform.scale;
    const radius = (Math.max(object.size[0], object.size[2]) * scale) / 2;
    const height = object.size[1] * scale;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity, depth = Infinity;
    for (const cx of [x - radius, x + radius]) for (const cy of [y, y + height]) for (const cz of [z - radius, z + radius]) {
      const p = this.project([cx, cy, cz]);
      if (!p) return null;
      x0 = Math.min(x0, p.x); x1 = Math.max(x1, p.x); y0 = Math.min(y0, p.y); y1 = Math.max(y1, p.y);
      depth = Math.min(depth, p.depth);
    }
    return { x0, y0, x1, y1, depth };
  }

  pick(pointer: Point2, objects: InteractionObject[], margin: number): string | null {
    let best: { id: string; depth: number } | null = null;
    for (const object of objects) {
      const rect = this.screenRect(object);
      if (!rect) continue;
      if (pointer.x < rect.x0 - margin || pointer.x > rect.x1 + margin || pointer.y < rect.y0 - margin || pointer.y > rect.y1 + margin) continue;
      if (!best || rect.depth < best.depth) best = { id: object.id, depth: rect.depth };
    }
    return best?.id ?? null;
  }
}
