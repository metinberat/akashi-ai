// Imperative input runtime for Spatial Lab: owns the active hand provider, the
// gesture pipeline, the gesture→command controller and the session recorder.
// React components hold one instance and feed it settings; per-frame work never
// goes through React state except the small hands signal.

import { DEFAULT_CALIBRATION, imageToViewport, viewportToImage, type CameraCalibration } from "@/lib/spatial/calibration";
import type { SpatialFailure } from "@/lib/spatial/client";
import { SpatialGestureController, type ControllerOptions, type PreviewSink } from "@/lib/spatial/controller";
import { DEFAULT_GESTURE_CONFIG } from "@/lib/spatial/gesture/config";
import type { HandFrame } from "@/lib/spatial/gesture/hand";
import type { InteractionScene } from "@/lib/spatial/gesture/interaction";
import { GesturePipeline } from "@/lib/spatial/gesture/pipeline";
import type { PerspectiveProjector } from "@/lib/spatial/projection";
import { MediaPipeHandProvider } from "@/lib/spatial/providers/mediapipe";
import { HandRecorder, RecordedHandProvider, validateRecording, type HandRecording } from "@/lib/spatial/providers/recorded";
import { PointerHandProvider } from "@/lib/spatial/providers/synthetic";
import { TouchHandProvider, touchGestureConfig } from "@/lib/spatial/providers/touch";
import type { HandInputProvider, ProviderStatus } from "@/lib/spatial/providers/types";
import type { SpatialSceneStore } from "@/lib/spatial/scene-store";
import type { Signal } from "@/lib/spatial/signal";
import type { Capabilities, SceneState } from "@/lib/spatial/types";

import type { HandsFrame } from "./spatial-panels";

export type InputMode = "off" | "camera" | "simulated" | "recorded" | "touch";

export type RuntimeCallbacks = {
  onStatus: (status: ProviderStatus, label: string, mode: InputMode) => void;
  onHover: (objectId: string | null) => void;
  onNotice: (message: string) => void;
  onError: (failure: SpatialFailure) => void;
  onCalibration: (calibration: CameraCalibration) => void;
};

export type RuntimeSettings = {
  calibration: CameraCalibration;
  capabilities: Capabilities | null;
  sessionId: string | null;
  viewport: { width: number; height: number };
  paused: boolean;
};

export function interactionScene(view: SceneState, capabilities: Capabilities | null): InteractionScene {
  const limits = capabilities?.limits ?? { position_min: [-4, -1, -4] as [number, number, number], position_max: [4, 4, 2] as [number, number, number], scale_min: 0.1, scale_max: 10 };
  return {
    objects: view.order.map((id) => view.objects[id]).map((o) => ({ id: o.id, transform: o.transform, size: o.asset.normalization.size, visible: o.visible })),
    selection: view.selection,
    limits: { position_min: limits.position_min, position_max: limits.position_max, scale_min: limits.scale_min, scale_max: limits.scale_max },
  };
}

export class SpatialInputRuntime {
  private calibration: CameraCalibration = DEFAULT_CALIBRATION;
  private capabilities: Capabilities | null = null;
  private sessionId: string | null = null;
  private viewport = { width: 1280, height: 720 };
  private paused = false;
  private renderer: { setInteractive(value: boolean): void } | null = null;
  readonly pipeline: GesturePipeline;
  private touchPipeline: GesturePipeline | null = null;
  private active: GesturePipeline;
  private previewSink: PreviewSink | null = null;
  readonly controller: SpatialGestureController;
  private provider: HandInputProvider | null = null;
  private recorder: HandRecorder | null = null;
  private generation = 0;

  constructor(private readonly store: SpatialSceneStore, api: ControllerOptions["api"], private readonly projector: PerspectiveProjector,
              private readonly hands: Signal<HandsFrame>, private readonly callbacks: RuntimeCallbacks) {
    this.pipeline = new GesturePipeline(DEFAULT_GESTURE_CONFIG, projector, () => this.provider?.kind === "live" && this.calibration.swapHandedness);
    this.active = this.pipeline;
    this.controller = new SpatialGestureController({
      api,
      store,
      preview: () => this.previewSink,
      sessionId: () => this.sessionId,
      provider: () => this.provider?.id ?? "unknown",
      onError: (failure) => callbacks.onError(failure),
      onRefused: (reason) => {
        this.active.cancel(reason, performance.now());
        callbacks.onNotice(reason === "object_busy" ? "That object is held by another input right now." : `Manipulation refused (${reason}).`);
      },
    });
  }

  configure(settings: Partial<RuntimeSettings>): void {
    if (settings.calibration) this.calibration = settings.calibration;
    if (settings.capabilities !== undefined) this.capabilities = settings.capabilities;
    if (settings.sessionId !== undefined) this.sessionId = settings.sessionId;
    if (settings.viewport) this.viewport = settings.viewport;
    if (settings.paused !== undefined) this.paused = settings.paused;
  }

  attachRenderer(renderer: { setInteractive(value: boolean): void } | null): void {
    this.renderer = renderer;
  }

  /** Live preview channel (remote presence) so other viewers see held objects move. */
  setPreviewSink(sink: PreviewSink | null): void {
    this.previewSink = sink;
  }

  get providerId(): string | null {
    return this.provider?.id ?? null;
  }

  providerMetrics() {
    return this.provider?.metrics() ?? null;
  }

  private readonly onFrame = (frame: HandFrame) => {
    this.recorder?.push(frame);
    const view = this.store.view();
    if (!view || this.paused) return;
    const image = { width: frame.width, height: frame.height };
    const out = this.active.process(frame, interactionScene(view, this.capabilities), (p) => imageToViewport(p, image, this.viewport, this.calibration));
    this.controller.handle(out.intents);
    this.controller.presence(out.hands, this.projector);
    for (const intent of out.intents) if (intent.type === "hover") this.callbacks.onHover(intent.objectId);
    this.hands.set({ hands: out.hands, poses: out.poses, interaction: out.interaction, metrics: out.metrics });
    this.renderer?.setInteractive(out.hands.length > 0);
  };

  stop(): void {
    this.generation += 1;
    this.provider?.stop();
    this.provider = null;
    this.active.reset();
    this.active = this.pipeline;
    this.hands.set({ hands: [], poses: [], interaction: null, metrics: null });
    this.renderer?.setInteractive(false);
  }

  async start(mode: InputMode, options: { video?: HTMLVideoElement | null; stage?: HTMLElement | null; deviceId?: string; recording?: File; delegate?: "GPU" | "CPU" }): Promise<void> {
    this.stop();
    const generation = this.generation;
    if (mode === "off") {
      this.callbacks.onStatus({ state: "idle" }, "none", "off");
      return;
    }
    let provider: HandInputProvider;
    if (mode === "camera") {
      if (!options.video) return;
      provider = new MediaPipeHandProvider({ video: options.video, deviceId: options.deviceId || undefined, delegate: options.delegate });
    } else if (mode === "simulated") {
      if (!options.stage) return;
      provider = new PointerHandProvider(options.stage, (p) => viewportToImage(p, { width: 1280, height: 720 }, this.viewport, this.calibration));
    } else if (mode === "touch") {
      if (!options.stage) return;
      // Touch needs no settle/dwell (fingers are not noisy detections): its own tuned pipeline.
      this.touchPipeline ??= new GesturePipeline(touchGestureConfig(), this.projector, () => false);
      this.active = this.touchPipeline;
      provider = new TouchHandProvider(options.stage, (p) => viewportToImage(p, { width: 1280, height: 720 }, this.viewport, this.calibration));
    } else {
      if (!options.recording) return;
      let parsed: HandRecording;
      try {
        parsed = validateRecording(JSON.parse(await options.recording.text()));
      } catch (error) {
        this.callbacks.onStatus({ state: "error", code: "recording_invalid", message: error instanceof Error ? error.message : "Recording rejected" }, "recording", "off");
        return;
      }
      if (parsed.calibration) {
        this.calibration = parsed.calibration;
        this.callbacks.onCalibration(parsed.calibration);
      }
      provider = new RecordedHandProvider(parsed);
    }
    if (generation !== this.generation) return;
    this.provider = provider;
    provider.onStatus((status) => this.callbacks.onStatus(status, provider.label, status.state === "error" ? "off" : mode));
    this.callbacks.onStatus(provider.status(), provider.label, mode);
    try {
      await provider.start(this.onFrame);
    } catch {
      // The provider status carries the reason; scene input by UI/language continues.
      if (this.provider === provider) this.provider = null;
    }
  }

  startRecording(): void {
    this.recorder = new HandRecorder(3600);
  }

  get recording(): boolean {
    return this.recorder !== null;
  }

  /** Frames captured so far, or null when not recording. */
  get recordedFrames(): number | null {
    return this.recorder?.size ?? null;
  }

  stopRecording(): HandRecording | null {
    const recorder = this.recorder;
    this.recorder = null;
    if (!recorder || !recorder.size) return null;
    const provider = this.provider;
    const metrics = provider?.metrics();
    return recorder.export({ provider: provider?.id ?? "unknown", kind: provider?.kind ?? "synthetic", device: metrics?.device, delegate: metrics?.delegate }, this.calibration);
  }

  dispose(): void {
    this.stop();
    this.controller.dispose();
  }
}
