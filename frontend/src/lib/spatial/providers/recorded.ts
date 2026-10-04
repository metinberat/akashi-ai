// Recorded hand sessions: capture real provider output locally, then replay it
// deterministically (same frames, same timestamps) in tests and tuning.
// Corrupt or out-of-bounds recordings are rejected, never "best effort" replayed.

import type { CameraCalibration } from "../calibration.ts";
import { validObservation, type HandFrame, type HandObservation, type ProviderKind } from "../gesture/hand.ts";
import { browserClock } from "./synthetic.ts";
import { StatusEmitter, type HandInputProvider, type ProviderMetrics, type ProviderStatus } from "./types.ts";

export const RECORDING_SCHEMA = "akashi.spatial.hand-recording/1";
export const MAX_RECORDING_FRAMES = 20_000;

export type RecordedFrame = { t: number; hands: HandObservation[]; inferenceMs?: number };

export type HandRecording = {
  schema: typeof RECORDING_SCHEMA;
  created_at: string;
  source: { provider: string; kind: ProviderKind; device?: string; delegate?: string; resolution: { width: number; height: number }; notes?: string };
  calibration?: CameraCalibration;
  frames: RecordedFrame[];
};

export class RecordingInvalid extends Error {
  constructor(readonly reason: string, readonly frame?: number) {
    super(`Hand recording rejected: ${reason}${frame !== undefined ? ` (frame ${frame})` : ""}`);
  }
}

export function validateRecording(value: unknown): HandRecording {
  if (!value || typeof value !== "object") throw new RecordingInvalid("not an object");
  const recording = value as HandRecording;
  if (recording.schema !== RECORDING_SCHEMA) throw new RecordingInvalid("unsupported schema");
  const resolution = recording.source?.resolution;
  if (!resolution || !(resolution.width > 0 && resolution.width <= 8192) || !(resolution.height > 0 && resolution.height <= 8192)) {
    throw new RecordingInvalid("source resolution is missing or out of range");
  }
  if (!Array.isArray(recording.frames) || recording.frames.length === 0 || recording.frames.length > MAX_RECORDING_FRAMES) {
    throw new RecordingInvalid(`frame count must be 1-${MAX_RECORDING_FRAMES}`);
  }
  let previous = -Infinity;
  recording.frames.forEach((frame, index) => {
    if (!frame || !Number.isFinite(frame.t) || frame.t < 0 || frame.t < previous) throw new RecordingInvalid("timestamps must be finite and non-decreasing", index);
    previous = frame.t;
    if (!Array.isArray(frame.hands) || frame.hands.length > 4 || !frame.hands.every(validObservation)) throw new RecordingInvalid("invalid hand data", index);
    if (frame.inferenceMs !== undefined && !(Number.isFinite(frame.inferenceMs) && frame.inferenceMs >= 0)) throw new RecordingInvalid("invalid inference time", index);
  });
  return recording;
}

/** Deterministic frames for tests: identical input on every run. */
export function recordingFrames(recording: HandRecording, startAt = 0): HandFrame[] {
  const { width, height } = recording.source.resolution;
  return recording.frames.map((frame, index) => ({
    timestamp: startAt + frame.t, width, height, hands: frame.hands, source: "recorded", frameId: index + 1, inferenceMs: frame.inferenceMs,
  }));
}

export class RecordedHandProvider implements HandInputProvider {
  readonly id: string;
  readonly kind = "recorded" as const;
  readonly label: string;
  private emitter = new StatusEmitter();
  private cancel: (() => void) | null = null;
  private delivered = 0;
  private startedAt = 0;

  constructor(private readonly recording: HandRecording, private readonly options: { speed?: number; loop?: boolean; clock?: typeof browserClock } = {}) {
    validateRecording(recording);
    this.id = "recorded:" + recording.created_at;
    this.label = `Recorded hands (${recording.frames.length} frames, ${recording.source.provider})`;
  }

  status(): ProviderStatus { return this.emitter.get(); }
  onStatus(listener: (status: ProviderStatus) => void) { return this.emitter.subscribe(listener); }

  metrics(): ProviderMetrics {
    const clock = this.options.clock ?? browserClock;
    const seconds = Math.max((clock.now() - this.startedAt) / 1000, 1e-3);
    return { sourceFps: this.delivered / seconds, deliveredFps: this.delivered / seconds, skippedFrames: 0, inferenceMs: null,
      resolution: this.recording.source.resolution, device: this.recording.source.device };
  }

  async start(onFrame: (frame: HandFrame) => void): Promise<void> {
    const clock = this.options.clock ?? browserClock;
    const speed = this.options.speed ?? 1;
    const frames = recordingFrames(this.recording);
    const first = frames[0].timestamp;
    const duration = frames[frames.length - 1].timestamp - first;
    let index = 0;
    let loopOffset = 0;
    this.startedAt = clock.now();
    this.delivered = 0;
    this.emitter.set({ state: "running" });
    this.cancel = clock.every(4, () => {
      const elapsed = (clock.now() - this.startedAt) * speed;
      while (index < frames.length && frames[index].timestamp - first + loopOffset <= elapsed) {
        const frame = frames[index];
        onFrame({ ...frame, timestamp: this.startedAt + (frame.timestamp - first + loopOffset) / speed });
        this.delivered += 1;
        index += 1;
      }
      if (index >= frames.length) {
        if (this.options.loop) {
          index = 0;
          loopOffset += duration + 33;
        } else {
          this.stop();
        }
      }
    });
  }

  stop(): void {
    this.cancel?.();
    this.cancel = null;
    this.emitter.set({ state: "stopped" });
  }
}

export class HandRecorder {
  private frames: RecordedFrame[] = [];
  private origin: number | null = null;
  private resolution = { width: 0, height: 0 };

  constructor(private readonly maxFrames = 3600) {}

  get size(): number {
    return this.frames.length;
  }

  push(frame: HandFrame): boolean {
    if (this.frames.length >= this.maxFrames) return false;
    this.origin ??= frame.timestamp;
    this.resolution = { width: frame.width, height: frame.height };
    this.frames.push({ t: Math.round((frame.timestamp - this.origin) * 1000) / 1000, hands: frame.hands, inferenceMs: frame.inferenceMs });
    return true;
  }

  export(source: { provider: string; kind: ProviderKind; device?: string; delegate?: string; notes?: string }, calibration?: CameraCalibration): HandRecording {
    return validateRecording({
      schema: RECORDING_SCHEMA,
      created_at: new Date().toISOString(),
      source: { ...source, resolution: this.resolution },
      calibration,
      frames: this.frames,
    });
  }

  clear(): void {
    this.frames = [];
    this.origin = null;
  }
}
