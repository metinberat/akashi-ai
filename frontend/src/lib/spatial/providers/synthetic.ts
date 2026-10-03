// Synthetic providers (SYNTHETIC input, clearly labelled in the UI):
// * ScriptedHandProvider — deterministic timeline for demos and tests.
// * PointerHandProvider  — a simulated hand that follows the mouse: button =
//   pinch, "2" toggles a mirrored second hand for two-hand scale/rotate. It
//   drives the real tracker/pose/interaction pipeline without a camera.

import type { HandFrame } from "../gesture/hand.ts";
import { OPEN_RIGHT, jitter, syntheticHand, type SyntheticHandPose } from "../gesture/synthetic.ts";
import { StatusEmitter, type HandInputProvider, type ProviderMetrics, type ProviderStatus } from "./types.ts";

type Clock = { now(): number; every(ms: number, fn: () => void): () => void };

export const browserClock: Clock = {
  now: () => performance.now(),
  every: (ms, fn) => {
    const handle = setInterval(fn, ms);
    return () => clearInterval(handle);
  },
};

const WIDTH = 1280;
const HEIGHT = 720;
const ASPECT = WIDTH / HEIGHT;

export type Script = (elapsedMs: number) => SyntheticHandPose[];

export class ScriptedHandProvider implements HandInputProvider {
  readonly kind = "synthetic" as const;
  readonly label: string;
  private emitter = new StatusEmitter();
  private cancel: (() => void) | null = null;
  private delivered = 0;
  private startedAt = 0;

  constructor(readonly id: string, private readonly script: Script, private readonly options: { fps?: number; noise?: number; seed?: number; clock?: Clock; label?: string } = {}) {
    this.label = options.label ?? "Scripted synthetic hands";
  }

  status(): ProviderStatus { return this.emitter.get(); }
  onStatus(listener: (status: ProviderStatus) => void) { return this.emitter.subscribe(listener); }

  metrics(): ProviderMetrics {
    const clock = this.options.clock ?? browserClock;
    const seconds = Math.max((clock.now() - this.startedAt) / 1000, 1e-3);
    return { sourceFps: this.delivered / seconds, deliveredFps: this.delivered / seconds, skippedFrames: 0, inferenceMs: null, resolution: { width: WIDTH, height: HEIGHT } };
  }

  async start(onFrame: (frame: HandFrame) => void): Promise<void> {
    const clock = this.options.clock ?? browserClock;
    const noise = this.options.noise ? jitter(this.options.seed ?? 1, this.options.noise) : undefined;
    this.startedAt = clock.now();
    this.delivered = 0;
    this.emitter.set({ state: "running" });
    this.cancel = clock.every(1000 / (this.options.fps ?? 30), () => {
      const now = clock.now();
      const hands = this.script(now - this.startedAt).map((pose) => syntheticHand(pose, ASPECT, noise));
      this.delivered += 1;
      onFrame({ timestamp: now, width: WIDTH, height: HEIGHT, hands, source: "synthetic", frameId: this.delivered });
    });
  }

  stop(): void {
    this.cancel?.();
    this.cancel = null;
    this.emitter.set({ state: "stopped" });
  }
}

/** Inverse of the default mirrored selfie mapping: simulated hands are placed in image space. */
export type ViewportToImage = (point: { x: number; y: number }) => { x: number; y: number };

export class PointerHandProvider implements HandInputProvider {
  readonly id = "pointer-simulated";
  readonly kind = "synthetic" as const;
  readonly label = "Simulated hands (mouse)";
  private emitter = new StatusEmitter();
  private cancel: (() => void) | null = null;
  private pointer: { x: number; y: number } | null = null;
  private pressed = false;
  private twoHands = false;
  private delivered = 0;
  private startedAt = 0;
  private detach: (() => void) | null = null;

  constructor(private readonly surface: HTMLElement, private readonly toImage: ViewportToImage, private readonly clock: Clock = browserClock) {}

  status(): ProviderStatus { return this.emitter.get(); }
  onStatus(listener: (status: ProviderStatus) => void) { return this.emitter.subscribe(listener); }
  get twoHandMode(): boolean { return this.twoHands; }

  metrics(): ProviderMetrics {
    const seconds = Math.max((this.clock.now() - this.startedAt) / 1000, 1e-3);
    return { sourceFps: this.delivered / seconds, deliveredFps: this.delivered / seconds, skippedFrames: 0, inferenceMs: null, resolution: { width: WIDTH, height: HEIGHT } };
  }

  async start(onFrame: (frame: HandFrame) => void): Promise<void> {
    const rect = () => this.surface.getBoundingClientRect();
    const move = (event: PointerEvent) => {
      const r = rect();
      this.pointer = { x: (event.clientX - r.left) / r.width, y: (event.clientY - r.top) / r.height };
    };
    const down = (event: PointerEvent) => { if (event.button === 0) { move(event); this.pressed = true; } };
    const up = () => { this.pressed = false; };
    const leave = () => { this.pointer = null; this.pressed = false; };
    const key = (event: KeyboardEvent) => { if (event.key === "2" && !(event.target instanceof HTMLInputElement) && !(event.target instanceof HTMLTextAreaElement)) this.twoHands = !this.twoHands; };
    this.surface.addEventListener("pointermove", move);
    this.surface.addEventListener("pointerdown", down);
    window.addEventListener("pointerup", up);
    this.surface.addEventListener("pointerleave", leave);
    window.addEventListener("keydown", key);
    this.detach = () => {
      this.surface.removeEventListener("pointermove", move);
      this.surface.removeEventListener("pointerdown", down);
      window.removeEventListener("pointerup", up);
      this.surface.removeEventListener("pointerleave", leave);
      window.removeEventListener("keydown", key);
    };
    this.startedAt = this.clock.now();
    this.emitter.set({ state: "running" });
    this.cancel = this.clock.every(1000 / 30, () => {
      const now = this.clock.now();
      const hands = [];
      if (this.pointer) {
        hands.push(this.hand(this.pointer, "Right"));
        if (this.twoHands) hands.push(this.hand({ x: 1 - this.pointer.x, y: this.pointer.y }, "Left"));
      }
      this.delivered += 1;
      onFrame({ timestamp: now, width: WIDTH, height: HEIGHT, hands, source: "synthetic", frameId: this.delivered });
    });
  }

  private hand(target: { x: number; y: number }, handedness: "Left" | "Right") {
    const pose: SyntheticHandPose = { ...OPEN_RIGHT, handedness, pinch: this.pressed ? 1 : 0 };
    // Place the palm so the thumb/index midpoint lands exactly under the mouse.
    // The viewport↔image mapping is affine, so one correction in image space is exact.
    const wanted = this.toImage(target);
    const probe = syntheticHand({ ...pose, center: wanted }, ASPECT);
    const tip = { x: (probe.landmarks[4].x + probe.landmarks[8].x) / 2, y: (probe.landmarks[4].y + probe.landmarks[8].y) / 2 };
    return syntheticHand({ ...pose, center: { x: 2 * wanted.x - tip.x, y: 2 * wanted.y - tip.y } }, ASPECT);
  }

  stop(): void {
    this.cancel?.();
    this.cancel = null;
    this.detach?.();
    this.detach = null;
    this.emitter.set({ state: "stopped" });
  }
}
