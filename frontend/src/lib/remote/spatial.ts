// Spatial Lab over a remote session.
//
// Core stays authoritative: this keeps a SpatialSceneStore replica in sync by
// history revision (snapshot or ordered event patches), mirrors other devices'
// live previews of held objects, and exposes the same port the gesture
// controller uses over HTTP — so touch, camera gestures, UI and voice on a
// remote device all become ordinary Spatial requests that Core validates,
// records (with this device's provenance) and fans out to every viewer.

import { applyPatches, ReplayInconsistent } from "../spatial/replay.ts";
import type { SpatialSceneStore } from "../spatial/scene-store.ts";
import type { CommandResult, Lease, Origin, Patch, SceneState, SessionInfo, Snapshot, SpatialRequest, Transform, Vec3 } from "../spatial/types.ts";
import { RemoteFailure } from "./protocol.ts";
import type { RemoteSessionClient } from "./session.ts";

export type OriginSummary = {
  kind: string;
  provider?: string;
  en: string;
  tr: string;
  device?: { id?: string; name?: string; type?: string };
  session?: string;
  modality?: string;
  approval?: Record<string, unknown>;
};

export type CompactEvent = {
  seq: number;
  kind: "command" | "undo" | "redo";
  category: string | null;
  at: string;
  command: string;
  targets: string[];
  summary: string | null;
  patches: Patch[];
  digest_before: string;
  digest_after: string;
  undoes: number | null;
  redoes: number | null;
  origin: OriginSummary;
};

export type RemoteLease = Lease & { holder?: { device_name?: string; device_type?: string; session?: string; modality?: string; kind?: string } };
export type RosterEntry = {
  session: string;
  device: { id: string; name: string; device_type: string; kind: string };
  state: string;
  scopes: string[];
  transport: string | null;
  capabilities: Array<{ name: string; state: string; detail: Record<string, unknown> }>;
  cursors: Array<{ hand: string; position: Vec3; state: string }>;
};
export type RemotePresence = { session: string; device: RosterEntry["device"]; anchors: Record<string, { position: Vec3; confidence: number }>; at: number };

export type Modality = "gesture" | "touch" | "pointer" | "language" | "voice" | "ui";

type SyncBody = {
  session_id: string;
  mode: "snapshot" | "events";
  snapshot?: Snapshot;
  events?: CompactEvent[];
  revision: number;
  digest: string;
  leases: RemoteLease[];
  previews: Array<{ lease_id: string; object_id: string; transform: Transform }>;
  roster: RosterEntry[];
  session: SessionInfo;
};

export function modalityFor(origin: Origin | undefined): Modality {
  const provider = origin?.provider ?? "";
  if (origin?.kind === "language") return Boolean(origin.input?.voice) ? "voice" : "language";
  if (origin?.kind === "ui") return "ui";
  if (provider.startsWith("touch")) return "touch";
  if (provider.startsWith("pointer")) return "pointer";
  return "gesture";
}

export class RemoteSpatial {
  sessionId: string | null;
  leases: RemoteLease[] = [];
  roster: RosterEntry[] = [];
  history: CompactEvent[] = [];
  presence = new Map<string, RemotePresence>();
  syncing = false;
  resyncs = 0;
  lastSyncMode: "snapshot" | "events" | null = null;
  failure: RemoteFailure | null = null;
  version = 0;
  private buffer: CompactEvent[][] = [];
  private remotePreviews = new Map<string, string>();
  private listeners = new Set<() => void>();
  private unsubscribers: Array<() => void> = [];
  private revisionWaiters: Array<{ revision: number; resolve: () => void }> = [];
  private subscribing: Promise<void> | null = null;

  constructor(private readonly client: RemoteSessionClient, private readonly store: SpatialSceneStore,
              private readonly options: { sessionId?: string | null; create?: boolean; modality?: () => Modality } = {}) {
    this.sessionId = options.sessionId ?? null;
  }

  start(): () => void {
    const c = this.client;
    this.unsubscribers.push(
      c.onSession(() => { void this.subscribe(); }),
      c.on("resync_required", () => { void this.subscribe(); }),
      c.on("spatial.events", (m) => this.onEvents(m.body.events as CompactEvent[])),
      c.on("spatial.preview", (m) => this.onPreview(m.body as { lease_id: string; object_id: string; transform?: Transform; ended?: boolean })),
      c.on("spatial.leases", (m) => this.onLeases(m.body.leases as RemoteLease[])),
      c.on("spatial.roster", (m) => { this.roster = m.body.roster as RosterEntry[]; this.bump(); }),
      c.on("spatial.presence", (m) => {
        const body = m.body as Omit<RemotePresence, "at">;
        this.presence.set(body.session, { ...body, at: this.client.clock.now() });
        this.bump();
      }),
      c.on("spatial.session", (m) => this.onSessionInfo(m.body.session as SessionInfo)),
      c.on("spatial.unsubscribed", () => { this.failure = new RemoteFailure("forbidden", "Viewing permission was removed."); this.bump(); }),
    );
    if (c.state === "online") void this.subscribe();
    return () => this.stop();
  }

  stop(): void {
    for (const off of this.unsubscribers.splice(0)) off();
    for (const objectId of this.remotePreviews.values()) this.store.clearPreview(objectId);
    this.remotePreviews.clear();
  }

  subscribeTo(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private bump(): void {
    this.version += 1;
    for (const listener of this.listeners) listener();
  }

  // Synchronization --------------------------------------------------------------------
  subscribe(): Promise<void> {
    if (this.subscribing) return this.subscribing;
    this.syncing = true;
    this.bump();
    const current = this.store.current;
    const known = current && (!this.sessionId || current.session.id === this.sessionId);
    const body: Record<string, unknown> = { ...(this.sessionId ? { session_id: this.sessionId } : {}), ...(this.options.create ? { create: true } : {}) };
    if (known) Object.assign(body, { session_id: current!.session.id, revision: current!.session.revision, digest: current!.session.digest });
    this.subscribing = this.client.request("spatial.subscribe", body)
      .then((ack) => this.applySync(ack as unknown as SyncBody))
      .catch((error) => {
        this.failure = error instanceof RemoteFailure ? error : new RemoteFailure("sync_failed", String(error));
        this.syncing = false;
        this.buffer = [];
        this.bump();
      })
      .finally(() => { this.subscribing = null; });
    return this.subscribing;
  }

  private applySync(body: SyncBody): void {
    this.sessionId = body.session_id;
    this.failure = null;
    this.lastSyncMode = body.mode;
    this.resyncs += 1;
    if (body.mode === "snapshot" && body.snapshot) {
      this.store.apply(body.snapshot, true);
      this.history = [];
    } else if (body.events) {
      this.applyEvents(body.events, false);
    }
    this.syncing = false;
    const buffered = this.buffer.splice(0);
    for (const events of buffered) this.applyEvents(events, false);
    this.onSessionInfo(body.session);
    this.onLeases(body.leases);
    for (const preview of body.previews) this.onPreview(preview);
    this.roster = body.roster;
    this.bump();
  }

  private onEvents(events: CompactEvent[]): void {
    if (this.syncing) {
      this.buffer.push(events);
      return;
    }
    this.applyEvents(events, true);
  }

  /** Apply events strictly by revision; a gap or inconsistency triggers a re-sync, never a guess. */
  private applyEvents(events: CompactEvent[], resyncOnGap: boolean): void {
    let snapshot = this.store.current;
    if (!snapshot) {
      if (resyncOnGap) void this.subscribe();
      return;
    }
    let state: SceneState = snapshot.state;
    let session = snapshot.session;
    let changed = false;
    for (const event of events) {
      if (event.seq <= session.revision) continue;
      if (event.seq !== session.revision + 1) {
        if (changed) this.store.apply({ session, state });
        if (resyncOnGap) void this.subscribe();
        return;
      }
      try {
        state = applyPatches(state as unknown as Record<string, unknown>, event.patches, event.seq) as unknown as SceneState;
      } catch (error) {
        if (error instanceof ReplayInconsistent) {
          if (changed) this.store.apply({ session, state });
          void this.subscribe();
          return;
        }
        throw error;
      }
      session = { ...session, revision: event.seq, digest: event.digest_after };
      this.history.push(event);
      if (this.history.length > 60) this.history.shift();
      changed = true;
    }
    if (changed) {
      snapshot = { session, state };
      this.store.apply(snapshot);
      this.resolveWaiters();
      this.bump();
    }
  }

  private onSessionInfo(info: SessionInfo | undefined): void {
    if (!info) return;
    const current = this.store.current;
    if (current && info.id === current.session.id && info.revision === current.session.revision) {
      this.store.applySession({ ...info });
      this.bump();
    }
  }

  private onLeases(leases: RemoteLease[]): void {
    this.leases = leases ?? [];
    const live = new Set(this.leases.map((lease) => lease.id));
    for (const [leaseId, objectId] of [...this.remotePreviews]) {
      if (!live.has(leaseId)) {
        this.remotePreviews.delete(leaseId);
        this.store.clearPreview(objectId);
      }
    }
    this.bump();
  }

  private onPreview(preview: { lease_id: string; object_id: string; transform?: Transform; ended?: boolean }): void {
    if (preview.ended || !preview.transform) {
      if (this.remotePreviews.delete(preview.lease_id)) this.store.clearPreview(preview.object_id);
      return;
    }
    this.remotePreviews.set(preview.lease_id, preview.object_id);
    this.store.setPreview(preview.object_id, preview.transform);
  }

  isRemotelyHeld(objectId: string): boolean {
    return [...this.remotePreviews.values()].includes(objectId);
  }

  waitForRevision(revision: number, timeoutMs = 1500): Promise<void> {
    if (this.store.revision >= revision) return Promise.resolve();
    return new Promise((resolve) => {
      const entry = { revision, resolve };
      this.revisionWaiters.push(entry);
      this.client.clock.setTimeout(() => {
        const index = this.revisionWaiters.indexOf(entry);
        if (index >= 0) {
          this.revisionWaiters.splice(index, 1);
          void this.subscribe();  // the event was lost or delayed: re-read rather than guess
          resolve();
        }
      }, timeoutMs);
    });
  }

  private resolveWaiters(): void {
    const revision = this.store.revision;
    const ready = this.revisionWaiters.filter((w) => w.revision <= revision);
    this.revisionWaiters = this.revisionWaiters.filter((w) => w.revision > revision);
    for (const waiter of ready) waiter.resolve();
  }

  // Requests -------------------------------------------------------------------------
  async command(request: SpatialRequest, modality: Modality, input?: Record<string, unknown>, baseRevision: number | null = this.store.revision): Promise<CommandResult> {
    const ack = await this.client.request("spatial.command", {
      request, modality, ...(input ? { input } : {}), ...(baseRevision !== null && baseRevision >= 0 ? { base_revision: baseRevision } : {}),
    }) as { status: CommandResult["status"]; revision: number; targets: string[]; notes: string[]; token?: string; question?: string };
    if (ack.status === "applied") await this.waitForRevision(ack.revision);
    return { status: ack.status, revision: ack.revision, targets: ack.targets, notes: ack.notes, token: ack.token, question: ack.question,
             snapshot: this.store.current! };
  }

  interpret(text: string, modality: "language" | "voice" = "language") {
    return this.client.request("spatial.interpret", { text, modality });
  }

  confirm(token: string, accept: boolean) {
    return this.client.request("spatial.confirm", { token, accept });
  }

  provenance(objectId: string) {
    return this.client.request("spatial.provenance", { object_id: objectId });
  }

  /** The port SpatialGestureController drives (same shape as the HTTP SpatialApi subset). */
  port() {
    const modality = () => this.options.modality?.() ?? "gesture";
    return {
      command: (_session: string, request: SpatialRequest, origin: Origin) =>
        this.command(request, origin.kind === "gesture" ? modality() : modalityFor(origin), origin.input),
      beginLease: async (_session: string, objectId: string): Promise<Lease> =>
        await this.client.request("spatial.lease.begin", { object_id: objectId, modality: modality(), base_revision: this.store.revision }) as unknown as Lease,
      renewLease: async (_session: string, leaseId: string): Promise<Lease> => {
        this.client.send("spatial.lease.renew", { lease_id: leaseId });
        return { id: leaseId, object_id: "", origin: "remote", expires_in: 4 };
      },
      endLease: async (_session: string, leaseId: string) => await this.client.request("spatial.lease.end", { lease_id: leaseId }) as { ended: boolean },
      presence: async (_session: string, anchors: Partial<Record<"left_hand" | "right_hand", { position: Vec3; confidence: number }>>) => {
        this.client.send("spatial.presence", { anchors });
        return {};
      },
      preview: (_session: string, leaseId: string, _objectId: string, transform: Transform) => {
        this.client.send("spatial.preview", { lease_id: leaseId, transform });
      },
    };
  }
}
