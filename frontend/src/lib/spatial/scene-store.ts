// Client replica of the authoritative scene. The backend owns state; this
// store holds the latest snapshot (by revision) plus *explicit* transient
// previews for objects currently held by a hand. The renderer draws
// view() = snapshot with previews applied, so there is one source of truth and
// one clearly-scoped, short-lived overlay — never a competing shadow scene.

import type { SceneState, Snapshot, Transform } from "./types.ts";
import { cloneTransform } from "./math.ts";

export class SpatialSceneStore {
  private snapshot: Snapshot | null = null;
  private previews = new Map<string, Transform>();
  private listeners = new Set<() => void>();
  private cached: { version: number; view: SceneState | null } = { version: -1, view: null };
  version = 0;

  get current(): Snapshot | null {
    return this.snapshot;
  }

  get revision(): number {
    return this.snapshot?.session.revision ?? -1;
  }

  /** Accept a snapshot unless it is older than what we already hold. ``force`` is for an
   *  authoritative re-sync (Core may have restored a different history). */
  apply(snapshot: Snapshot, force = false): boolean {
    if (!force && this.snapshot && snapshot.session.id === this.snapshot.session.id && snapshot.session.revision < this.snapshot.session.revision) {
      return false;
    }
    this.snapshot = snapshot;
    for (const id of [...this.previews.keys()]) if (!snapshot.state.objects[id]) this.previews.delete(id);
    this.bump();
    return true;
  }

  /** Session metadata changed without a scene change (e.g. a lease expired). */
  applySession(session: Snapshot["session"]): void {
    if (!this.snapshot || session.id !== this.snapshot.session.id || session.revision !== this.snapshot.session.revision) return;
    this.snapshot = { ...this.snapshot, session };
    this.bump();
  }

  setPreview(objectId: string, transform: Transform): void {
    this.previews.set(objectId, cloneTransform(transform));
    this.bump();
  }

  clearPreview(objectId: string): void {
    if (this.previews.delete(objectId)) this.bump();
  }

  hasPreview(objectId: string): boolean {
    return this.previews.has(objectId);
  }

  view(): SceneState | null {
    if (this.cached.version === this.version) return this.cached.view;
    let view: SceneState | null = null;
    if (this.snapshot) {
      view = this.snapshot.state;
      if (this.previews.size) {
        const objects = { ...view.objects };
        for (const [id, transform] of this.previews) {
          if (objects[id]) objects[id] = { ...objects[id], transform };
        }
        view = { ...view, objects };
      }
    }
    this.cached = { version: this.version, view };
    return view;
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private bump(): void {
    this.version += 1;
    for (const listener of this.listeners) listener();
  }
}
