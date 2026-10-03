// Input provider abstraction. The gesture pipeline never knows which provider
// produced a frame: a live camera, a recording or a synthetic generator all
// emit the same HandFrame. This is what lets cloud tests exercise the full
// downstream logic without a webcam, and lets local acceptance replay real
// recorded sessions deterministically.

import type { HandFrame, ProviderKind } from "../gesture/hand.ts";

export type ProviderStatus =
  | { state: "idle" }
  | { state: "starting"; detail: string }
  | { state: "running" }
  | { state: "stopped" }
  | { state: "error"; code: ProviderErrorCode; message: string };

export type ProviderErrorCode =
  | "camera_denied" | "camera_unavailable" | "camera_busy" | "model_missing" | "runtime_unavailable"
  | "unsupported" | "recording_invalid" | "internal";

export type ProviderMetrics = {
  /** New camera/source frames per second (before inference). */
  sourceFps: number;
  /** Frames handed to the pipeline per second. */
  deliveredFps: number;
  /** Source frames skipped because the previous inference was still running. */
  skippedFrames: number;
  inferenceMs: number | null;
  device?: string;
  resolution?: { width: number; height: number };
  delegate?: string;
};

export interface HandInputProvider {
  readonly id: string;
  readonly kind: ProviderKind;
  readonly label: string;
  status(): ProviderStatus;
  metrics(): ProviderMetrics;
  start(onFrame: (frame: HandFrame) => void): Promise<void>;
  stop(): void;
  onStatus(listener: (status: ProviderStatus) => void): () => void;
}

export class StatusEmitter {
  private current: ProviderStatus = { state: "idle" };
  private listeners = new Set<(status: ProviderStatus) => void>();

  get(): ProviderStatus {
    return this.current;
  }

  set(status: ProviderStatus): void {
    this.current = status;
    for (const listener of this.listeners) listener(status);
  }

  subscribe(listener: (status: ProviderStatus) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}
