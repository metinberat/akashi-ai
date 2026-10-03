// Live webcam provider: getUserMedia (video only) + MediaPipe Hand Landmarker
// (Apache-2.0), running locally in the renderer. No frames leave the machine.
//
// Assets are served from the app origin (local-first, works offline):
//   ./spatial/mediapipe/vision_wasm_internal.{js,wasm} (copied from node_modules)
//   ./spatial/models/hand_landmarker.task             (fetched once, SHA-256 pinned)
// See frontend/scripts/spatial-assets.mjs. Real-camera behaviour is LOCAL
// ACCEPTANCE REQUIRED; the cloud only validated this path with Chromium's fake
// camera device fed with still hand photographs.

import type { HandFrame, HandObservation, Point3 } from "../gesture/hand.ts";
import { StatusEmitter, type HandInputProvider, type ProviderErrorCode, type ProviderMetrics, type ProviderStatus } from "./types.ts";

export type MediaPipeOptions = {
  video: HTMLVideoElement;
  deviceId?: string;
  width?: number;
  height?: number;
  frameRate?: number;
  numHands?: number;
  delegate?: "GPU" | "CPU";
  wasmBase?: string;
  modelPath?: string;
  minDetection?: number;
  minPresence?: number;
  minTracking?: number;
};

type Landmarker = {
  detectForVideo(video: HTMLVideoElement, timestamp: number): {
    landmarks: Point3[][];
    worldLandmarks: Point3[][];
    handedness?: Array<Array<{ score: number; categoryName: string }>>;
    handednesses?: Array<Array<{ score: number; categoryName: string }>>;
  };
  close(): void;
};

type VideoWithFrameCallback = HTMLVideoElement & {
  requestVideoFrameCallback?: (callback: (now: number, metadata: { presentedFrames: number; mediaTime: number }) => void) => number;
  cancelVideoFrameCallback?: (handle: number) => void;
};

export class ProviderError extends Error {
  constructor(readonly code: ProviderErrorCode, message: string) {
    super(message);
  }
}

export function cameraErrorCode(error: unknown): ProviderErrorCode {
  const name = (error as { name?: string })?.name ?? "";
  if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError") return "camera_denied";
  if (name === "NotReadableError" || name === "AbortError" || name === "TrackStartError") return "camera_busy";
  if (name === "NotFoundError" || name === "OverconstrainedError" || name === "DevicesNotFoundError") return "camera_unavailable";
  return "internal";
}

const CAMERA_MESSAGES: Partial<Record<ProviderErrorCode, string>> = {
  camera_denied: "Camera permission was denied. Allow camera access for AKASHI and retry.",
  camera_busy: "The camera is in use by another application or could not start.",
  camera_unavailable: "No suitable camera was found.",
};

export async function listCameras(): Promise<Array<{ deviceId: string; label: string }>> {
  if (!navigator.mediaDevices?.enumerateDevices) return [];
  const devices = await navigator.mediaDevices.enumerateDevices();
  return devices.filter((d) => d.kind === "videoinput").map((d, i) => ({ deviceId: d.deviceId, label: d.label || `Camera ${i + 1}` }));
}

export class MediaPipeHandProvider implements HandInputProvider {
  readonly id = "mediapipe-hands";
  readonly kind = "live" as const;
  readonly label = "Camera · MediaPipe Hand Landmarker";
  private emitter = new StatusEmitter();
  private stream: MediaStream | null = null;
  private landmarker: Landmarker | null = null;
  private frameHandle: number | null = null;
  private running = false;
  private lastPresented = 0;
  private sourceFrames = 0;
  private delivered = 0;
  private skipped = 0;
  private startedAt = 0;
  private inference: number | null = null;
  private delegate: string | undefined;

  constructor(private readonly options: MediaPipeOptions) {}

  status(): ProviderStatus { return this.emitter.get(); }
  onStatus(listener: (status: ProviderStatus) => void) { return this.emitter.subscribe(listener); }

  metrics(): ProviderMetrics {
    const seconds = Math.max((performance.now() - this.startedAt) / 1000, 1e-3);
    const track = this.stream?.getVideoTracks()[0];
    return {
      sourceFps: this.sourceFrames / seconds,
      deliveredFps: this.delivered / seconds,
      skippedFrames: this.skipped,
      inferenceMs: this.inference,
      device: track?.label,
      resolution: { width: this.options.video.videoWidth, height: this.options.video.videoHeight },
      delegate: this.delegate,
    };
  }

  async start(onFrame: (frame: HandFrame) => void): Promise<void> {
    if (this.running) return;
    const { video } = this.options;
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new ProviderError("unsupported", "This runtime has no camera API.");
      this.emitter.set({ state: "starting", detail: "Requesting camera" });
      try {
        this.stream = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: {
            deviceId: this.options.deviceId ? { exact: this.options.deviceId } : undefined,
            width: { ideal: this.options.width ?? 1280 },
            height: { ideal: this.options.height ?? 720 },
            frameRate: { ideal: this.options.frameRate ?? 30 },
          },
        });
      } catch (error) {
        const code = cameraErrorCode(error);
        throw new ProviderError(code, CAMERA_MESSAGES[code] ?? "The camera could not be opened.");
      }
      video.srcObject = this.stream;
      video.muted = true;
      video.playsInline = true;
      await video.play();
      this.emitter.set({ state: "starting", detail: "Loading hand model" });
      this.landmarker = await this.createLandmarker();
      this.running = true;
      this.startedAt = performance.now();
      this.sourceFrames = this.delivered = this.skipped = 0;
      this.emitter.set({ state: "running" });
      this.schedule(onFrame);
    } catch (error) {
      this.stop();
      const failure = error instanceof ProviderError ? error : new ProviderError("internal", "Hand tracking failed to start.");
      this.emitter.set({ state: "error", code: failure.code, message: failure.message });
      throw failure;
    }
  }

  private async createLandmarker(): Promise<Landmarker> {
    const base = (this.options.wasmBase ?? "./spatial/mediapipe").replace(/\/$/u, "");
    const modelPath = this.options.modelPath ?? "./spatial/models/hand_landmarker.task";
    const probe = await fetch(modelPath, { method: "GET", cache: "force-cache" }).catch(() => null);
    if (!probe || !probe.ok) {
      throw new ProviderError("model_missing", "The local hand model is not installed. Run `npm run spatial:assets` (see docs/spatial-lab.md).");
    }
    const model = new Uint8Array(await probe.arrayBuffer());
    let vision: typeof import("@mediapipe/tasks-vision");
    try {
      vision = await import("@mediapipe/tasks-vision");
    } catch {
      throw new ProviderError("runtime_unavailable", "The hand-tracking runtime could not be loaded.");
    }
    let fileset;
    try {
      fileset = await vision.FilesetResolver.forVisionTasks(base);
    } catch {
      throw new ProviderError("runtime_unavailable", "The hand-tracking WebAssembly runtime is missing. Run `npm run spatial:assets`.");
    }
    const create = (delegate: "GPU" | "CPU") => vision.HandLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetBuffer: model, delegate },
      runningMode: "VIDEO",
      numHands: this.options.numHands ?? 2,
      minHandDetectionConfidence: this.options.minDetection ?? 0.5,
      minHandPresenceConfidence: this.options.minPresence ?? 0.5,
      minTrackingConfidence: this.options.minTracking ?? 0.5,
    });
    const preferred = this.options.delegate ?? "GPU";
    try {
      const landmarker = await create(preferred);
      this.delegate = preferred;
      return landmarker as unknown as Landmarker;
    } catch {
      if (preferred === "CPU") throw new ProviderError("runtime_unavailable", "The hand model could not be initialised.");
      const landmarker = await create("CPU").catch(() => {
        throw new ProviderError("runtime_unavailable", "The hand model could not be initialised on GPU or CPU.");
      });
      this.delegate = "CPU (GPU fallback)";
      return landmarker as unknown as Landmarker;
    }
  }

  private schedule(onFrame: (frame: HandFrame) => void): void {
    const video = this.options.video as VideoWithFrameCallback;
    const process = (presentedFrames?: number) => {
      if (!this.running || !this.landmarker || video.readyState < 2) return;
      if (presentedFrames !== undefined) {
        const delta = presentedFrames - this.lastPresented;
        if (this.lastPresented && delta > 1) this.skipped += delta - 1;
        this.lastPresented = presentedFrames;
      }
      this.sourceFrames += 1;
      const timestamp = performance.now();
      const result = this.landmarker.detectForVideo(video, timestamp);
      this.inference = performance.now() - timestamp;
      const labels = result.handedness ?? result.handednesses ?? [];
      const hands: HandObservation[] = result.landmarks.map((landmarks, i) => ({
        handedness: labels[i]?.[0]?.categoryName === "Left" ? "Left" : "Right",
        handednessScore: labels[i]?.[0]?.score ?? 0,
        landmarks: landmarks.map((p) => ({ x: p.x, y: p.y, z: p.z })),
        worldLandmarks: result.worldLandmarks[i]?.map((p) => ({ x: p.x, y: p.y, z: p.z })),
      }));
      this.delivered += 1;
      onFrame({ timestamp, width: video.videoWidth, height: video.videoHeight, hands, source: "live", frameId: this.sourceFrames, inferenceMs: this.inference });
    };
    if (video.requestVideoFrameCallback) {
      const loop = (_now: number, metadata: { presentedFrames: number }) => {
        if (!this.running) return;
        process(metadata.presentedFrames);
        this.frameHandle = video.requestVideoFrameCallback!(loop);
      };
      this.frameHandle = video.requestVideoFrameCallback(loop);
    } else {
      let lastTime = -1;
      const loop = () => {
        if (!this.running) return;
        if (video.currentTime !== lastTime) {
          lastTime = video.currentTime;
          process();
        }
        this.frameHandle = requestAnimationFrame(loop);
      };
      this.frameHandle = requestAnimationFrame(loop);
    }
  }

  stop(): void {
    this.running = false;
    const video = this.options.video as VideoWithFrameCallback;
    if (this.frameHandle !== null) {
      if (video.cancelVideoFrameCallback) video.cancelVideoFrameCallback(this.frameHandle);
      cancelAnimationFrame(this.frameHandle);
      this.frameHandle = null;
    }
    this.landmarker?.close();
    this.landmarker = null;
    for (const track of this.stream?.getTracks() ?? []) track.stop();
    this.stream = null;
    video.srcObject = null;
    if (this.emitter.get().state !== "error") this.emitter.set({ state: "stopped" });
  }
}
