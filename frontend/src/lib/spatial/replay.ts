// Visual replay: reconstruct scene states from the backend's recorded patches.
// This applies recorded data generically (no domain logic), verifying each
// patch's recorded "before" value; inconsistent data stops replay instead of
// silently drawing a wrong state. Determinism of the domain itself is proven
// server-side by POST /spatial/sessions/{id}/replay/verify.

import type { Patch, SceneState, SpatialEvent } from "./types.ts";

export class ReplayInconsistent extends Error {
  constructor(readonly seq: number, reason: string) {
    super(`Replay data is inconsistent at event ${seq}: ${reason}`);
  }
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value as Record<string, unknown>).sort().map((k) => `${JSON.stringify(k)}:${canonical((value as Record<string, unknown>)[k])}`).join(",")}}`;
  }
  if (typeof value === "number" && Object.is(value, -0)) return "0";
  return JSON.stringify(value);
}

export function applyPatches<T extends Record<string, unknown>>(document: T, patches: Patch[], seq = 0): T {
  const result = structuredClone(document) as Record<string, unknown>;
  for (const patch of patches) {
    let parent = result as Record<string, unknown>;
    for (const key of patch.path.slice(0, -1)) {
      const next = parent[String(key)];
      if (!next || typeof next !== "object") throw new ReplayInconsistent(seq, `missing path ${patch.path.join(".")}`);
      parent = next as Record<string, unknown>;
    }
    const key = String(patch.path[patch.path.length - 1]);
    if (patch.op === "add") {
      if (key in parent) throw new ReplayInconsistent(seq, `add target exists at ${patch.path.join(".")}`);
      parent[key] = structuredClone(patch.after);
    } else if (patch.op === "remove") {
      if (!(key in parent) || canonical(parent[key]) !== canonical(patch.before)) throw new ReplayInconsistent(seq, `remove mismatch at ${patch.path.join(".")}`);
      delete parent[key];
    } else {
      if (!(key in parent) || canonical(parent[key]) !== canonical(patch.before)) throw new ReplayInconsistent(seq, `replace mismatch at ${patch.path.join(".")}`);
      parent[key] = structuredClone(patch.after);
    }
  }
  return result as T;
}

export type ReplayFrame = { seq: number; event: SpatialEvent | null; state: SceneState };

/** All intermediate states: frame 0 is the initial state, frame n is after event n. */
export function reconstruct(initial: SceneState, events: SpatialEvent[]): ReplayFrame[] {
  const frames: ReplayFrame[] = [{ seq: 0, event: null, state: initial }];
  let state = initial;
  events.forEach((event, index) => {
    if (event.seq !== index + 1) throw new ReplayInconsistent(event.seq, "events are not contiguous");
    state = applyPatches(state as unknown as Record<string, unknown>, event.patches, event.seq) as unknown as SceneState;
    frames.push({ seq: event.seq, event, state });
  });
  return frames;
}
