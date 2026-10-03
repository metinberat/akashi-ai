// Interaction state machine: stable hand poses → scene interaction intents.
//
//   idle ──hold start on object──▶ pressing ──release quickly, little motion──▶ select
//                                    │
//                                    └──moved or held──▶ manipulating (one hand: move)
//                                                         ├─ second hand holds ─▶ two hands: scale + yaw
//                                                         ├─ one of two releases ─▶ back to one hand (re-anchored)
//                                                         ├─ release ─▶ end (commit)
//                                                         └─ tracking lost > grace ─▶ end at last stable transform
//
// "Hold" means pinch or grab (fist). Movement is 2.5D: the object moves on the
// plane at its own depth (z); two-hand distance scales it and two-hand twist
// turns it about the vertical axis. No depth or contact is inferred.

import type { Limits, Transform, Vec3 } from "../types.ts";
import { add, clampTransform, cloneTransform, distance2, quantizeTransform, rotateWorldYaw, scaleVec, sub, transformsClose, type Point2 } from "../math.ts";
import type { GestureConfig } from "./config.ts";
import type { HandPose, PoseEvent } from "./poses.ts";
import type { TrackedHand } from "./tracker.ts";

export type InteractionObject = { id: string; transform: Transform; size: Vec3; visible: boolean };
export type InteractionScene = { objects: InteractionObject[]; selection: string[]; limits: Pick<Limits, "position_min" | "position_max" | "scale_min" | "scale_max"> };

export interface SceneProjector {
  pick(pointer: Point2, objects: InteractionObject[], margin: number): string | null;
  toWorld(pointer: Point2, planeZ: number): Vec3 | null;
}

export type ManipulationProvenance = {
  gesture: "one_hand_move" | "two_hand_scale_rotate" | "mixed";
  duration_ms: number;
  frames: number;
  hands: Array<{ track: number; handedness: string }>;
  mean_confidence: number;
  tracking_losses: number;
  spikes_absorbed: number;
  glitches_rejected: number;
};

export type InteractionIntent =
  | { type: "hover"; objectId: string | null; hand: number | null }
  | { type: "select"; objectId: string; hand: number; at: number }
  | { type: "manipulation.begin"; objectId: string; hand: number; transform: Transform; at: number }
  | { type: "manipulation.update"; objectId: string; transform: Transform; mode: "one_hand" | "two_hand"; at: number }
  | { type: "manipulation.end"; objectId: string; transform: Transform; reason: "release" | "tracking_lost"; provenance: ManipulationProvenance; at: number }
  | { type: "manipulation.cancel"; objectId: string; reason: string; at: number };

type Pressing = { kind: "pressing"; hand: number; objectId: string; startAt: number; startPointer: Point2; handScale: number };
type Manipulating = {
  kind: "manipulating";
  objectId: string;
  primary: number;
  secondary: number | null;
  base: Transform;
  anchor: Vec3;
  two: { p1: Vec3; p2: Vec3; base: Transform } | null;
  current: Transform;
  startAt: number;
  frames: number;
  oneHandFrames: number;
  twoHandFrames: number;
  hands: Map<number, string>;
  confidence: number;
  samples: number;
  losses: number;
  spikes: number;
  lastPointer: Map<number, Point2>;
  coasting: Set<number>;
  recent: Array<{ at: number; transform: Transform }>;
  glitchBase: Map<number, number>;
  glitchLatest: Map<number, number>;
};
type State = { kind: "idle" } | Pressing | Manipulating;

export type InteractionSnapshot = {
  mode: "idle" | "pressing" | "one_hand" | "two_hand";
  objectId: string | null;
  primary: number | null;
  secondary: number | null;
  hover: string | null;
};

export type InteractionInput = {
  now: number;
  hands: TrackedHand[];
  poses: HandPose[];
  events: PoseEvent[];
  lost: number[];
  scene: InteractionScene;
};

const holding = (pose: HandPose | undefined) => Boolean(pose && (pose.pinch || pose.grab));

export class InteractionEngine {
  private state: State = { kind: "idle" };
  private hover: string | null = null;

  constructor(private readonly config: GestureConfig, private readonly projector: SceneProjector) {}

  snapshot(): InteractionSnapshot {
    const s = this.state;
    if (s.kind === "idle") return { mode: "idle", objectId: null, primary: null, secondary: null, hover: this.hover };
    if (s.kind === "pressing") return { mode: "pressing", objectId: s.objectId, primary: s.hand, secondary: null, hover: this.hover };
    return { mode: s.secondary !== null ? "two_hand" : "one_hand", objectId: s.objectId, primary: s.primary, secondary: s.secondary, hover: this.hover };
  }

  /** External cancellation (e.g. Core refused the manipulation lease). */
  cancel(reason: string, now: number): InteractionIntent[] {
    const s = this.state;
    this.state = { kind: "idle" };
    return s.kind === "manipulating" ? [{ type: "manipulation.cancel", objectId: s.objectId, reason, at: now }] : [];
  }

  process(input: InteractionInput): InteractionIntent[] {
    const intents: InteractionIntent[] = [];
    const hands = new Map(input.hands.map((h) => [h.id, h]));
    const poses = new Map(input.poses.map((p) => [p.hand, p]));
    const objects = input.scene.objects.filter((o) => o.visible);
    const starts = input.events.filter((e) => e.kind === "start");
    const ends = new Set(input.events.filter((e) => e.kind === "end").map((e) => e.hand));
    const lost = new Set(input.lost);

    // Hover feedback follows the first observed hand that is not manipulating.
    const busy = this.state.kind === "manipulating" ? new Set([this.state.primary, this.state.secondary]) : new Set<number | null>();
    const hoverHand = input.hands.find((h) => h.state === "tracking" && !busy.has(h.id));
    const hover = hoverHand ? this.projector.pick(hoverHand.features.pointer, objects, this.config.pickMargin) : null;
    if (hover !== this.hover) {
      this.hover = hover;
      intents.push({ type: "hover", objectId: hover, hand: hoverHand?.id ?? null });
    }

    const s = this.state;
    if (s.kind === "idle") {
      for (const start of starts) {
        const hand = hands.get(start.hand);
        if (!hand || hand.state !== "tracking") continue;
        const target = this.projector.pick(hand.features.pointer, objects, this.config.pickMargin);
        if (!target) continue;
        this.state = { kind: "pressing", hand: hand.id, objectId: target, startAt: input.now, startPointer: hand.features.pointer, handScale: hand.features.scale };
        break;
      }
      return intents;
    }

    if (s.kind === "pressing") {
      const hand = hands.get(s.hand);
      const object = objects.find((o) => o.id === s.objectId);
      if (lost.has(s.hand) || !object) {
        this.state = { kind: "idle" };
        return intents;
      }
      if (!hand || hand.state !== "tracking") return intents;
      const moved = distance2(hand.features.pointer, s.startPointer) / Math.max(s.handScale, 1e-4);
      if (ends.has(s.hand) || !holding(poses.get(s.hand))) {
        if (input.now - s.startAt <= this.config.tap.maxMs && moved <= this.config.tap.maxMove) {
          intents.push({ type: "select", objectId: s.objectId, hand: s.hand, at: input.now });
        }
        this.state = { kind: "idle" };
        return intents;
      }
      if (moved >= this.config.drag.startMove || input.now - s.startAt >= this.config.drag.holdMs) {
        const anchor = this.projector.toWorld(s.startPointer, object.transform.position[2]);
        if (!anchor) return intents;
        if (!input.scene.selection.includes(object.id)) intents.push({ type: "select", objectId: object.id, hand: s.hand, at: input.now });
        const base = cloneTransform(object.transform);
        this.state = {
          kind: "manipulating", objectId: object.id, primary: s.hand, secondary: null, base, anchor, two: null,
          current: cloneTransform(base), startAt: s.startAt, frames: 0, oneHandFrames: 0, twoHandFrames: 0,
          hands: new Map([[hand.id, hand.handedness]]), confidence: 0, samples: 0, losses: 0, spikes: 0,
          lastPointer: new Map([[hand.id, hand.features.pointer]]), coasting: new Set(), recent: [],
          glitchBase: new Map([[hand.id, hand.glitches]]), glitchLatest: new Map([[hand.id, hand.glitches]]),
        };
        intents.push({ type: "manipulation.begin", objectId: object.id, hand: hand.id, transform: cloneTransform(base), at: input.now });
        this.manipulate(this.state, hands, input, intents);
      }
      return intents;
    }

    // Manipulating -----------------------------------------------------------------
    if (!input.scene.objects.some((o) => o.id === s.objectId)) {
      this.state = { kind: "idle" };
      intents.push({ type: "manipulation.cancel", objectId: s.objectId, reason: "object_removed", at: input.now });
      return intents;
    }
    if (s.secondary === null) {
      const join = starts.find((e) => e.hand !== s.primary && hands.get(e.hand)?.state === "tracking");
      if (join) {
        s.secondary = join.hand;
        s.hands.set(join.hand, hands.get(join.hand)!.handedness);
        s.glitchBase.set(join.hand, hands.get(join.hand)!.glitches);
        s.lastPointer.set(join.hand, hands.get(join.hand)!.features.pointer);
        this.reanchor(s, hands);
      }
    }
    const primaryGone = lost.has(s.primary) || ends.has(s.primary) || !holding(poses.get(s.primary));
    const secondaryGone = s.secondary !== null && (lost.has(s.secondary) || ends.has(s.secondary) || !holding(poses.get(s.secondary)));
    if ((primaryGone && !lost.has(s.primary)) || (secondaryGone && !lost.has(s.secondary!))) this.lookBack(s, input.now);
    if (secondaryGone) {
      s.secondary = null;
      this.reanchor(s, hands);
    }
    if (primaryGone) {
      if (s.secondary !== null) {
        s.primary = s.secondary;
        s.secondary = null;
        this.reanchor(s, hands);
      } else {
        this.state = { kind: "idle" };
        intents.push(this.finish(s, lost.has(s.primary) ? "tracking_lost" : "release", input.now));
        return intents;
      }
    }
    this.manipulate(s, hands, input, intents);
    return intents;
  }

  /**
   * Opening the fingers moves the thumb/index midpoint during the release dwell.
   * Restore the transform from just before the release started, so letting go
   * does not nudge the object.
   */
  private lookBack(s: Manipulating, now: number): void {
    const cutoff = now - Math.max(this.config.pinch.exitDwellMs, this.config.grab.exitDwellMs);
    const before = [...s.recent].reverse().find((entry) => entry.at <= cutoff);
    if (before) s.current = cloneTransform(before.transform);
    s.recent = [];
  }

  private reanchor(s: Manipulating, hands: Map<number, TrackedHand>): void {
    s.base = cloneTransform(s.current);
    const primary = hands.get(s.primary);
    const z = s.current.position[2];
    if (primary) {
      s.anchor = this.projector.toWorld(primary.features.pointer, z) ?? s.anchor;
      s.lastPointer.set(primary.id, primary.features.pointer);
    }
    const secondary = s.secondary !== null ? hands.get(s.secondary) : undefined;
    if (primary && secondary) {
      const p1 = this.projector.toWorld(primary.features.pointer, z);
      const p2 = this.projector.toWorld(secondary.features.pointer, z);
      s.two = p1 && p2 ? { p1, p2, base: cloneTransform(s.current) } : null;
      s.lastPointer.set(secondary.id, secondary.features.pointer);
    } else {
      s.two = null;
    }
  }

  private manipulate(s: Manipulating, hands: Map<number, TrackedHand>, input: InteractionInput, intents: InteractionIntent[]): void {
    const involved = [s.primary, ...(s.secondary !== null ? [s.secondary] : [])].map((id) => hands.get(id));
    for (const hand of involved) if (hand) s.glitchLatest.set(hand.id, hand.glitches);
    for (const hand of involved) {
      if (!hand || hand.state !== "tracking") {
        if (hand && !s.coasting.has(hand.id)) {
          s.coasting.add(hand.id);
          s.losses += 1;
        }
        return; // Freeze at the last stable transform while a hand is not observed.
      }
      s.coasting.delete(hand.id);
    }
    const spiked = involved.some((hand) => distance2(hand!.features.pointer, s.lastPointer.get(hand!.id) ?? hand!.features.pointer) > this.config.spikeMove);
    if (spiked) {
      // A one-frame jump is a tracking glitch, not intent: keep the object where it
      // is and continue relative to the new pointer position.
      s.spikes += 1;
      this.reanchor(s, hands);
      return;
    }
    for (const hand of involved) s.lastPointer.set(hand!.id, hand!.features.pointer);
    s.frames += 1;
    s.samples += involved.length;
    s.confidence += involved.reduce((sum, hand) => sum + hand!.score, 0);
    const z = s.base.position[2];
    let next: Transform;
    if (s.secondary !== null && s.two) {
      const w1 = this.projector.toWorld(involved[0]!.features.pointer, z);
      const w2 = this.projector.toWorld(involved[1]!.features.pointer, z);
      if (!w1 || !w2) return;
      const v0 = sub(s.two.p2, s.two.p1);
      const v = sub(w2, w1);
      const d0 = Math.hypot(v0[0], v0[1]);
      let ratio = d0 > 1e-4 ? Math.hypot(v[0], v[1]) / d0 : 1;
      if (Math.abs(ratio - 1) < this.config.twoHand.scaleDeadband) ratio = 1;
      let delta = Math.atan2(v[1], v[0]) - Math.atan2(v0[1], v0[0]);
      delta = Math.atan2(Math.sin(delta), Math.cos(delta));
      if (Math.abs(delta) < this.config.twoHand.rotateDeadband) delta = 0;
      const shift = sub(scaleVec(add(w1, w2), 0.5), scaleVec(add(s.two.p1, s.two.p2), 0.5));
      next = {
        position: add(s.two.base.position, [shift[0], shift[1], 0]),
        rotation: rotateWorldYaw(s.two.base.rotation, this.config.twoHand.rotationSign * delta),
        scale: s.two.base.scale * ratio,
      };
      s.twoHandFrames += 1;
    } else {
      const world = this.projector.toWorld(involved[0]!.features.pointer, z);
      if (!world) return;
      const delta = sub(world, s.anchor);
      next = { position: add(s.base.position, [delta[0], delta[1], 0]), rotation: s.base.rotation, scale: s.base.scale };
      s.oneHandFrames += 1;
    }
    next = clampTransform(next, input.scene.limits);
    s.recent.push({ at: input.now, transform: cloneTransform(next) });
    if (s.recent.length > 24) s.recent.shift();
    if (!transformsClose(next, s.current, this.config.updateEpsilon)) {
      s.current = next;
      intents.push({ type: "manipulation.update", objectId: s.objectId, transform: cloneTransform(next), mode: s.secondary !== null ? "two_hand" : "one_hand", at: input.now });
    }
  }

  private finish(s: Manipulating, reason: "release" | "tracking_lost", now: number): InteractionIntent {
    return {
      type: "manipulation.end",
      objectId: s.objectId,
      transform: quantizeTransform(s.current),
      reason,
      at: now,
      provenance: {
        gesture: s.twoHandFrames === 0 ? "one_hand_move" : s.oneHandFrames > s.twoHandFrames / 4 ? "mixed" : "two_hand_scale_rotate",
        duration_ms: Math.round(now - s.startAt),
        frames: s.frames,
        hands: [...s.hands].map(([track, handedness]) => ({ track, handedness })),
        mean_confidence: s.samples ? Math.round((s.confidence / s.samples) * 1000) / 1000 : 0,
        tracking_losses: s.losses,
        spikes_absorbed: s.spikes,
        glitches_rejected: [...s.glitchLatest].reduce((sum, [id, count]) => sum + count - (s.glitchBase.get(id) ?? count), 0),
      },
    };
  }
}
