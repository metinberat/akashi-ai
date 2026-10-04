// Typed client for the Spatial Lab API. Every call goes through the shared
// apiFetch, so the desktop IPC bridge, bearer handling and HTTPS rules apply.

import { ApiError, apiFetch, type BackendConfig } from "../api.ts";
import type {
  AssetSummary, Capabilities, CommandResult, FormProject, FormVersion, InterpretResult, Lease, Origin,
  SceneState, SessionInfo, Snapshot, SpatialEvent, SpatialRequest,
} from "./types.ts";

export type SpatialFailure = {
  code: string;
  message: string;
  kind?: string;
  question?: string;
  candidates?: Array<{ id: string; label: string; why: string; position?: string }>;
  status?: number;
};

export function spatialFailure(error: unknown): SpatialFailure {
  if (error instanceof ApiError) {
    const payload = error.payload ?? {};
    return {
      code: typeof payload.code === "string" ? payload.code : error.kind,
      message: typeof payload.detail === "string" ? payload.detail : error.message,
      kind: typeof payload.kind === "string" ? payload.kind : undefined,
      question: typeof payload.question === "string" ? payload.question : undefined,
      candidates: Array.isArray(payload.candidates) ? payload.candidates as SpatialFailure["candidates"] : undefined,
      status: error.status,
    };
  }
  return { code: "unknown", message: error instanceof Error ? error.message : String(error) };
}

async function json<T>(config: BackendConfig, path: string, init: RequestInit = {}): Promise<T> {
  const response = await apiFetch(config, path, {
    ...init,
    headers: init.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json", ...init.headers } : init.headers,
  });
  return response.json() as Promise<T>;
}

const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });
const enc = encodeURIComponent;

export interface SpatialApi {
  capabilities(): Promise<Capabilities>;
  createSession(label?: string): Promise<Snapshot>;
  listSessions(): Promise<{ sessions: Array<{ id: string; label: string; created_at: string | null; revision: number | null; readable: boolean }> }>;
  getSession(id: string, since?: number): Promise<({ changed: true } & Snapshot) | { changed: false; session: SessionInfo }>;
  command(id: string, request: SpatialRequest, origin: Origin, confirmed?: boolean): Promise<CommandResult>;
  confirm(id: string, token: string, accept: boolean): Promise<CommandResult>;
  interpret(id: string, text: string, voice?: boolean): Promise<InterpretResult>;
  beginLease(id: string, objectId: string): Promise<Lease>;
  renewLease(id: string, leaseId: string): Promise<Lease>;
  endLease(id: string, leaseId: string): Promise<{ ended: boolean }>;
  presence(id: string, anchors: Partial<Record<"left_hand" | "right_hand", { position: [number, number, number]; confidence: number }>>): Promise<unknown>;
  events(id: string, after?: number): Promise<{ session_id: string; revision: number; initial_state: SceneState | null; events: SpatialEvent[] }>;
  verifyReplay(id: string): Promise<{ verified: boolean; events: number; final_digest: string; live_digest: string; matches_live_state: boolean }>;
  metrics(): Promise<{ submit_ms: { count: number; p50: number | null; p95: number | null; max: number | null }; counters: Record<string, number> }>;
  assets(): Promise<{ assets: AssetSummary[] }>;
  uploadAsset(file: File): Promise<AssetSummary>;
  assetContent(assetId: string): Promise<ArrayBuffer>;
  formProjects(): Promise<{ available: boolean; reason?: string; projects: FormProject[] }>;
  formVersions(projectId: string): Promise<{ versions: FormVersion[] }>;
}

export function spatialApi(config: BackendConfig): SpatialApi {
  return {
    capabilities: () => json(config, "/spatial/capabilities"),
    createSession: (label = "Spatial Lab") => json(config, "/spatial/sessions", post({ label })),
    listSessions: () => json(config, "/spatial/sessions"),
    getSession: (id, since) => json(config, `/spatial/sessions/${enc(id)}?client=true${since !== undefined ? `&since=${since}` : ""}`),
    command: (id, request, origin, confirmed = false) => json(config, `/spatial/sessions/${enc(id)}/commands`, post({ request, origin, confirmed })),
    confirm: (id, token, accept) => json(config, `/spatial/sessions/${enc(id)}/confirmations/${enc(token)}`, post({ accept })),
    interpret: (id, text, voice = false) => json(config, `/spatial/sessions/${enc(id)}/interpret`, post({ text, voice })),
    beginLease: (id, objectId) => json(config, `/spatial/sessions/${enc(id)}/leases`, post({ object_id: objectId, origin: "gesture" })),
    renewLease: (id, leaseId) => json(config, `/spatial/sessions/${enc(id)}/leases/${enc(leaseId)}/renew`, { method: "POST" }),
    endLease: (id, leaseId) => json(config, `/spatial/sessions/${enc(id)}/leases/${enc(leaseId)}`, { method: "DELETE" }),
    presence: (id, anchors) => json(config, `/spatial/sessions/${enc(id)}/presence`, { method: "PUT", body: JSON.stringify({ anchors }) }),
    events: (id, after = 0) => json(config, `/spatial/sessions/${enc(id)}/events?after=${after}&limit=500`),
    verifyReplay: (id) => json(config, `/spatial/sessions/${enc(id)}/replay/verify`, { method: "POST" }),
    metrics: () => json(config, "/spatial/metrics"),
    assets: () => json(config, "/spatial/assets"),
    uploadAsset: (file) => {
      const form = new FormData();
      form.append("file", file, file.name);
      return json(config, "/spatial/assets", { method: "POST", body: form });
    },
    assetContent: async (assetId) => (await apiFetch(config, `/spatial/assets/${enc(assetId)}/content`)).arrayBuffer(),
    formProjects: () => json(config, "/spatial/form/projects"),
    formVersions: (projectId) => json(config, `/spatial/form/projects/${enc(projectId)}/versions`),
  };
}
