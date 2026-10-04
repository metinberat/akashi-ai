// Per-hand pose state machines with hysteresis, dwell time, cooldown and
// settle time. A pose starts only after the metric stays past the *enter*
// threshold for enterDwellMs, and ends only after it stays past the *exit*
// threshold for exitDwellMs. The gap between thresholds absorbs jitter around a
// single value; dwell absorbs one-frame spikes; cooldown stops release/regrab
// chatter; settle ignores the noisy first frames of a newly detected hand.
// While a hand is coasting (not observed) or degraded (low score), state is
// frozen: tracking noise never creates or ends a pose by itself.

import type { GestureConfig, HysteresisConfig } from "./config.ts";
import type { TrackedHand } from "./tracker.ts";

export type PoseName = "pinch" | "grab";
export type PoseEvent = { hand: number; pose: PoseName; kind: "start" | "end"; at: number };

class Hysteresis {
  active = false;
  since = 0;
  private candidateSince: number | null = null;
  private cooldownUntil = -Infinity;

  constructor(private readonly config: HysteresisConfig, private readonly lowerIsActive: boolean) {}

  update(metric: number, now: number, allowStart: boolean): "start" | "end" | null {
    const enter = this.lowerIsActive ? metric < this.config.enter : metric > this.config.enter;
    const exit = this.lowerIsActive ? metric > this.config.exit : metric < this.config.exit;
    if (!this.active) {
      if (!enter || !allowStart || now < this.cooldownUntil) {
        this.candidateSince = null;
        return null;
      }
      this.candidateSince ??= now;
      if (now - this.candidateSince >= this.config.enterDwellMs) {
        this.active = true;
        this.since = now;
        this.candidateSince = null;
        return "start";
      }
      return null;
    }
    if (!exit) {
      this.candidateSince = null;
      return null;
    }
    this.candidateSince ??= now;
    if (now - this.candidateSince >= this.config.exitDwellMs) {
      this.release(now);
      return "end";
    }
    return null;
  }

  release(now: number): void {
    this.active = false;
    this.candidateSince = null;
    this.cooldownUntil = now + this.config.cooldownMs;
  }
}

export type HandPose = { hand: number; pinch: boolean; grab: boolean; pinchSince: number | null; grabSince: number | null };

export class PoseClassifier {
  private machines = new Map<number, { pinch: Hysteresis; grab: Hysteresis }>();

  constructor(private readonly config: GestureConfig) {}

  reset(): void {
    this.machines.clear();
  }

  update(hands: TrackedHand[], lost: number[], now: number): { poses: HandPose[]; events: PoseEvent[] } {
    const events: PoseEvent[] = [];
    for (const id of lost) {
      const machine = this.machines.get(id);
      if (!machine) continue;
      if (machine.pinch.active) events.push({ hand: id, pose: "pinch", kind: "end", at: now });
      if (machine.grab.active) events.push({ hand: id, pose: "grab", kind: "end", at: now });
      this.machines.delete(id);
    }
    const poses: HandPose[] = [];
    for (const hand of hands) {
      let machine = this.machines.get(hand.id);
      if (!machine) {
        machine = { pinch: new Hysteresis(this.config.pinch, true), grab: new Hysteresis(this.config.grab, true) };
        this.machines.set(hand.id, machine);
      }
      const observed = hand.state === "tracking" && !hand.degraded;
      if (observed) {
        const settled = now - hand.firstSeen >= this.config.settleMs;
        const f = hand.features;
        // A pinch keeps the index finger partly extended; a fist curls it. This
        // keeps a closing fist (thumb near index) from registering as a pinch.
        const pinchMetric = f.indexExtension >= this.config.pinch.minIndexExtension ? f.pinchRatio : Math.max(f.pinchRatio, this.config.pinch.exit + 1);
        // Grab = every finger curled. Using the mean let a pointing hand (one finger
        // extended, three curled) register as a grab on real MediaPipe data.
        const grabEvent = machine.grab.update(f.maxExtension, now, settled && !machine.pinch.active);
        if (grabEvent) events.push({ hand: hand.id, pose: "grab", kind: grabEvent, at: now });
        const pinchEvent = machine.pinch.update(pinchMetric, now, settled && !machine.grab.active);
        if (pinchEvent) events.push({ hand: hand.id, pose: "pinch", kind: pinchEvent, at: now });
      }
      poses.push({
        hand: hand.id,
        pinch: machine.pinch.active,
        grab: machine.grab.active,
        pinchSince: machine.pinch.active ? machine.pinch.since : null,
        grabSince: machine.grab.active ? machine.grab.since : null,
      });
    }
    return { poses, events };
  }
}
