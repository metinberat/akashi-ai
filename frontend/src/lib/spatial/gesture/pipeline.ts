// HandFrame → tracked hands → stable poses → interaction intents, plus the
// measurements local acceptance needs (frame rate, processing time, gaps).
// The pipeline is provider-agnostic: live camera, recordings and synthetic
// hands all enter through the same HandFrame type.

import type { GestureConfig } from "./config.ts";
import type { HandFrame, ImageToViewport } from "./hand.ts";
import { InteractionEngine, type InteractionIntent, type InteractionScene, type InteractionSnapshot, type SceneProjector } from "./interaction.ts";
import { PoseClassifier, type HandPose, type PoseEvent } from "./poses.ts";
import { HandTracker, type TrackedHand } from "./tracker.ts";

export type PipelineMetrics = {
  frames: number;
  /** Exponential moving average of frames per second, from frame timestamps. */
  fps: number;
  /** Frames whose interval exceeded 2x the running average (dropped/stalled input). */
  gaps: number;
  processingMs: { last: number; p95: number };
  inferenceMs: { last: number | null; p95: number | null };
  handsVisible: number;
};

export type PipelineOutput = {
  hands: TrackedHand[];
  poses: HandPose[];
  events: PoseEvent[];
  intents: InteractionIntent[];
  interaction: InteractionSnapshot;
  metrics: PipelineMetrics;
};

function p95(values: number[]): number {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))];
}

export class GesturePipeline {
  readonly tracker: HandTracker;
  readonly poses: PoseClassifier;
  readonly interaction: InteractionEngine;
  private lastTimestamp: number | null = null;
  private interval = 0;
  private processing: number[] = [];
  private inference: number[] = [];
  private metrics: PipelineMetrics = { frames: 0, fps: 0, gaps: 0, processingMs: { last: 0, p95: 0 }, inferenceMs: { last: null, p95: null }, handsVisible: 0 };

  constructor(readonly config: GestureConfig, projector: SceneProjector, swapHandedness: () => boolean = () => false,
              private readonly clock: () => number = () => (typeof performance !== "undefined" ? performance.now() : Date.now())) {
    this.tracker = new HandTracker(config, swapHandedness);
    this.poses = new PoseClassifier(config);
    this.interaction = new InteractionEngine(config, projector);
  }

  reset(): void {
    this.tracker.reset();
    this.poses.reset();
    this.lastTimestamp = null;
    this.interval = 0;
  }

  process(frame: HandFrame, scene: InteractionScene, toViewport: ImageToViewport): PipelineOutput {
    const started = this.clock();
    const hands = this.tracker.update(frame, toViewport);
    const lost = this.tracker.lastEvents.lost;
    const { poses, events } = this.poses.update(hands, lost, frame.timestamp);
    const intents = this.interaction.process({ now: frame.timestamp, hands, poses, events, lost, scene });
    const elapsed = this.clock() - started;
    this.record(frame, elapsed, hands.filter((h) => h.state === "tracking").length);
    return { hands, poses, events, intents, interaction: this.interaction.snapshot(), metrics: { ...this.metrics } };
  }

  cancel(reason: string, now: number): InteractionIntent[] {
    return this.interaction.cancel(reason, now);
  }

  private record(frame: HandFrame, elapsed: number, visible: number): void {
    const m = this.metrics;
    m.frames += 1;
    m.handsVisible = visible;
    if (this.lastTimestamp !== null) {
      const delta = frame.timestamp - this.lastTimestamp;
      if (delta > 0) {
        if (this.interval > 0 && delta > this.interval * 2) m.gaps += 1;
        this.interval = this.interval ? this.interval * 0.9 + delta * 0.1 : delta;
        m.fps = 1000 / this.interval;
      }
    }
    this.lastTimestamp = frame.timestamp;
    this.processing = [...this.processing.slice(-299), elapsed];
    m.processingMs = { last: elapsed, p95: p95(this.processing) };
    if (frame.inferenceMs !== undefined) {
      this.inference = [...this.inference.slice(-299), frame.inferenceMs];
      m.inferenceMs = { last: frame.inferenceMs, p95: p95(this.inference) };
    }
  }
}
