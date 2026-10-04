// Touch input as hands: every finger on the screen becomes a pinching hand at that
// point, so one finger drags, a tap selects, and two fingers scale (spread) and
// turn (twist) through the SAME tracker → pose → interaction pipeline and the same
// gesture controller as camera hands. No second gesture implementation.
//
// A lifted finger is reported open for a few frames before it disappears, so the
// pose machine sees a clean release (not a tracking loss). Use touchGestureConfig():
// touches need no settle time or pinch dwell — they are not noisy detections.

import { gestureConfig, type GestureConfig } from "../gesture/config.ts";
import type { HandFrame } from "../gesture/hand.ts";
import { OPEN_RIGHT, syntheticHand, type SyntheticHandPose } from "../gesture/synthetic.ts";
import { browserClock, type ViewportToImage } from "./synthetic.ts";
import { StatusEmitter, type HandInputProvider, type ProviderMetrics, type ProviderStatus } from "./types.ts";

const WIDTH = 1280;
const HEIGHT = 720;
const ASPECT = WIDTH / HEIGHT;
const RELEASE_FRAMES = 4;

type Clock = { now(): number; every(ms: number, fn: () => void): () => void };

type Finger = { x: number; y: number; down: boolean; releaseFrames: number; handedness: "Left" | "Right" };

export function touchGestureConfig(): GestureConfig {
  return gestureConfig({
    settleMs: 0,
    pinch: { ...gestureConfig().pinch, enterDwellMs: 0, exitDwellMs: 20, cooldownMs: 40 },
    graceMs: 120,
  });
}

export type PointerLike = { pointerId: number; clientX: number; clientY: number; pointerType?: string; preventDefault?: () => void };

export class TouchHandProvider implements HandInputProvider {
  readonly id = "touch";
  readonly kind = "synthetic" as const;
  readonly label = "Touch";
  private emitter = new StatusEmitter();
  private fingers = new Map<number, Finger>();
  private cancel: (() => void) | null = null;
  private detach: (() => void) | null = null;
  private delivered = 0;
  private startedAt = 0;

  constructor(private readonly surface: { getBoundingClientRect(): { left: number; top: number; width: number; height: number };
                                          addEventListener: HTMLElement["addEventListener"]; removeEventListener: HTMLElement["removeEventListener"] } | null,
              private readonly toImage: ViewportToImage, private readonly clock: Clock = browserClock) {}

  status(): ProviderStatus { return this.emitter.get(); }
  onStatus(listener: (status: ProviderStatus) => void) { return this.emitter.subscribe(listener); }

  metrics(): ProviderMetrics {
    const seconds = Math.max((this.clock.now() - this.startedAt) / 1000, 1e-3);
    return { sourceFps: this.delivered / seconds, deliveredFps: this.delivered / seconds, skippedFrames: 0, inferenceMs: null,
             resolution: { width: WIDTH, height: HEIGHT } };
  }

  get activeTouches(): number {
    return [...this.fingers.values()].filter((f) => f.down).length;
  }

  private point(event: PointerLike): { x: number; y: number } {
    const rect = this.surface!.getBoundingClientRect();
    return { x: (event.clientX - rect.left) / rect.width, y: (event.clientY - rect.top) / rect.height };
  }

  // Exposed for tests and for surfaces that route events themselves.
  down(event: PointerLike): void {
    if (this.fingers.size >= 2 && !this.fingers.has(event.pointerId)) return;
    const used = new Set([...this.fingers.values()].map((f) => f.handedness));
    const handedness = used.has("Right") ? "Left" : "Right";
    this.fingers.set(event.pointerId, { ...this.point(event), down: true, releaseFrames: 0, handedness });
  }

  move(event: PointerLike): void {
    const finger = this.fingers.get(event.pointerId);
    if (finger && finger.down) Object.assign(finger, this.point(event));
  }

  up(event: PointerLike): void {
    const finger = this.fingers.get(event.pointerId);
    if (finger) {
      finger.down = false;
      finger.releaseFrames = RELEASE_FRAMES;
    }
  }

  async start(onFrame: (frame: HandFrame) => void): Promise<void> {
    if (this.surface) {
      const down = (event: PointerEvent) => { event.preventDefault(); this.down(event); };
      const move = (event: PointerEvent) => { if (this.fingers.has(event.pointerId)) event.preventDefault(); this.move(event); };
      const up = (event: PointerEvent) => this.up(event);
      this.surface.addEventListener("pointerdown", down as EventListener);
      this.surface.addEventListener("pointermove", move as EventListener);
      window.addEventListener("pointerup", up);
      window.addEventListener("pointercancel", up);
      this.detach = () => {
        this.surface!.removeEventListener("pointerdown", down as EventListener);
        this.surface!.removeEventListener("pointermove", move as EventListener);
        window.removeEventListener("pointerup", up);
        window.removeEventListener("pointercancel", up);
      };
    }
    this.startedAt = this.clock.now();
    this.emitter.set({ state: "running" });
    this.cancel = this.clock.every(1000 / 60, () => onFrame(this.frame()));
  }

  /** One frame of hands for the current touches (deterministic; used by tests directly). */
  frame(): HandFrame {
    const hands = [];
    for (const [id, finger] of [...this.fingers]) {
      if (!finger.down) {
        if (finger.releaseFrames <= 0) {
          this.fingers.delete(id);
          continue;
        }
        finger.releaseFrames -= 1;
      }
      hands.push(this.hand(finger));
    }
    this.delivered += 1;
    return { timestamp: this.clock.now(), width: WIDTH, height: HEIGHT, hands, source: "synthetic", frameId: this.delivered };
  }

  private hand(finger: Finger) {
    const pose: SyntheticHandPose = { ...OPEN_RIGHT, handedness: finger.handedness, pinch: finger.down ? 1 : 0 };
    // Put the pinch point (thumb/index midpoint) exactly under the finger.
    const wanted = this.toImage({ x: finger.x, y: finger.y });
    const probe = syntheticHand({ ...pose, center: wanted }, ASPECT);
    const tip = { x: (probe.landmarks[4].x + probe.landmarks[8].x) / 2, y: (probe.landmarks[4].y + probe.landmarks[8].y) / 2 };
    return syntheticHand({ ...pose, center: { x: 2 * wanted.x - tip.x, y: 2 * wanted.y - tip.y } }, ASPECT);
  }

  stop(): void {
    this.cancel?.();
    this.cancel = null;
    this.detach?.();
    this.detach = null;
    this.fingers.clear();
    this.emitter.set({ state: "stopped" });
  }
}
