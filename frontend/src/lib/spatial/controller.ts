// Gesture intents → the single Spatial Lab command path.
//
// select              → selection.select command (origin: gesture)
// manipulation.begin  → local preview + manipulation lease (blocks other origins)
// manipulation.update → local preview; with a live channel (remote presence) also a
//                       throttled, lossy preview so other viewers see the object move
// manipulation.end    → ONE object.transform "set" command carrying the lease and
//                       gesture provenance; the server validates and records it
// manipulation.cancel → release the lease, drop the preview (snap to server state)

import type { InteractionIntent, SceneProjector } from "./gesture/interaction.ts";
import type { TrackedHand } from "./gesture/tracker.ts";
import type { SpatialApi, SpatialFailure } from "./client.ts";
import { spatialFailure } from "./client.ts";
import type { SpatialSceneStore } from "./scene-store.ts";
import type { Origin, Transform, Vec3 } from "./types.ts";

export type PreviewSink = (session: string, leaseId: string, objectId: string, transform: Transform) => void;

export type ControllerOptions = {
  api: Pick<SpatialApi, "command" | "beginLease" | "renewLease" | "endLease" | "presence"> & { preview?: PreviewSink };
  /** Optional live preview channel when the command api itself has none (e.g. the owner's realtime session). */
  preview?: () => PreviewSink | null;
  /** Minimum interval between preview messages (ms). */
  previewIntervalMs?: number;
  store: SpatialSceneStore;
  sessionId: () => string | null;
  provider: () => string;
  onError: (failure: SpatialFailure) => void;
  /** The engine must reset when the server refuses a manipulation. */
  onRefused: (reason: string) => void;
  now?: () => number;
  every?: (ms: number, fn: () => void) => () => void;
};

type Active = { objectId: string; lease: Promise<string | null>; leaseId: string | null; stopRenew: (() => void) | null; startedAt: number; lastPreview: number };

export class SpatialGestureController {
  private queue: Promise<unknown> = Promise.resolve();
  private active: Active | null = null;
  private lastPresence = -Infinity;
  private lastAnchors = "";
  commits = 0;

  constructor(private readonly options: ControllerOptions) {}

  private origin(input: Record<string, unknown>): Origin {
    return { kind: "gesture", provider: this.options.provider(), input };
  }

  private enqueue<T>(work: () => Promise<T>): Promise<T | undefined> {
    const run = this.queue.then(work, work);
    this.queue = run.catch(() => undefined);
    return run.catch((error) => {
      this.options.onError(spatialFailure(error));
      return undefined;
    });
  }

  handle(intents: InteractionIntent[]): void {
    const session = this.options.sessionId();
    if (!session) return;
    for (const intent of intents) {
      if (intent.type === "select") {
        void this.enqueue(async () => {
          const result = await this.options.api.command(session, { type: "selection.select", target: { id: intent.objectId } }, this.origin({ gesture: "tap", hand: intent.hand }));
          if (result.snapshot) this.options.store.apply(result.snapshot);
        });
      } else if (intent.type === "manipulation.begin") {
        this.begin(session, intent.objectId, intent.transform);
      } else if (intent.type === "manipulation.update") {
        if (this.active?.objectId === intent.objectId) {
          this.options.store.setPreview(intent.objectId, intent.transform);
          this.streamPreview(session, this.active, intent.transform);
        }
      } else if (intent.type === "manipulation.end") {
        this.end(session, intent);
      } else if (intent.type === "manipulation.cancel") {
        this.cancel(session, intent.objectId);
      }
    }
  }

  private begin(session: string, objectId: string, transform: Parameters<SpatialSceneStore["setPreview"]>[1]): void {
    this.options.store.setPreview(objectId, transform);
    const lease = this.enqueue(async () => {
      try {
        const granted = await this.options.api.beginLease(session, objectId);
        const every = this.options.every ?? ((ms, fn) => { const h = setInterval(fn, ms); return () => clearInterval(h); });
        if (this.active?.objectId === objectId) {
          this.active.leaseId = granted.id;
          this.active.stopRenew = every(1500, () => { void this.options.api.renewLease(session, granted.id).catch(() => undefined); });
        }
        return granted.id;
      } catch (error) {
        const failure = spatialFailure(error);
        this.options.store.clearPreview(objectId);
        if (this.active?.objectId === objectId) this.active = null;
        this.options.onRefused(failure.code);
        throw error;
      }
    }).then((id) => id ?? null);
    this.active = { objectId, lease, leaseId: null, stopRenew: null, startedAt: (this.options.now ?? Date.now)(), lastPreview: -Infinity };
  }

  private streamPreview(session: string, active: Active, transform: Parameters<SpatialSceneStore["setPreview"]>[1]): void {
    const sink = this.options.api.preview ?? this.options.preview?.() ?? null;
    if (!sink || !active.leaseId) return;
    const now = (this.options.now ?? Date.now)();
    if (now - active.lastPreview < (this.options.previewIntervalMs ?? 33)) return;
    active.lastPreview = now;
    sink(session, active.leaseId, active.objectId, transform);
  }

  private end(session: string, intent: Extract<InteractionIntent, { type: "manipulation.end" }>): void {
    const active = this.active;
    if (!active || active.objectId !== intent.objectId) return;
    this.active = null;
    void this.enqueue(async () => {
      const leaseId = await active.lease;
      active.stopRenew?.();
      if (!leaseId) {
        this.options.store.clearPreview(intent.objectId);
        return;
      }
      try {
        const result = await this.options.api.command(session, {
          type: "object.transform", target: { id: intent.objectId }, mode: "set", transform: intent.transform, lease_id: leaseId,
        }, this.origin({ ...intent.provenance, ended_by: intent.reason }));
        if (result.snapshot) this.options.store.apply(result.snapshot);
        this.commits += 1;
      } finally {
        this.options.store.clearPreview(intent.objectId);
      }
    });
  }

  private cancel(session: string, objectId: string): void {
    const active = this.active;
    this.active = null;
    this.options.store.clearPreview(objectId);
    if (!active) return;
    void this.enqueue(async () => {
      const leaseId = await active.lease;
      active.stopRenew?.();
      if (leaseId) await this.options.api.endLease(session, leaseId);
    });
  }

  /** Publish hand anchors (projected onto the z=0 interaction plane) at ≤ 4 Hz. */
  presence(hands: TrackedHand[], projector: SceneProjector): void {
    const session = this.options.sessionId();
    const now = (this.options.now ?? Date.now)();
    if (!session || now - this.lastPresence < 250) return;
    const anchors: Partial<Record<"left_hand" | "right_hand", { position: Vec3; confidence: number }>> = {};
    for (const hand of hands) {
      if (hand.state !== "tracking") continue;
      const world = projector.toWorld(hand.features.pointer, 0);
      if (!world) continue;
      const key = hand.handedness === "Right" ? "right_hand" : "left_hand";
      anchors[key] = { position: world.map((v) => Math.round(v * 1000) / 1000) as Vec3, confidence: Math.round(hand.score * hand.handednessConfidence * 100) / 100 };
    }
    const signature = JSON.stringify(anchors);
    if (signature === this.lastAnchors && now - this.lastPresence < 1000) return;
    if (signature === "{}" && this.lastAnchors === "{}") return;
    this.lastPresence = now;
    this.lastAnchors = signature;
    void this.options.api.presence(session, anchors).catch(() => undefined);
  }

  dispose(): void {
    this.active?.stopRenew?.();
    this.active = null;
  }
}
