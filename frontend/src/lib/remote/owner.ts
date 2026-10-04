// Owner side of remote presence (desktop / web with the AKASHI API token).
//
// Management goes through the normal authenticated API. The owner's own
// realtime session uses the HTTP transport through apiFetch, so on the desktop
// it rides the IPC bridge (the token never reaches the renderer and CSP
// connect-src stays 'self'). In a plain browser the owner may use WebSocket.

import { ApiError, apiFetch, isDesktopRuntime, type BackendConfig } from "../api.ts";
import type { Approval, CapabilityReport, Welcome } from "./protocol.ts";
import { RemoteFailure } from "./protocol.ts";
import { RemoteSessionClient } from "./session.ts";
import { HttpTransport, WebSocketTransport, type HttpRequest } from "./transport.ts";

export type PresenceSession = {
  id: string;
  kind: string;
  state: string;
  scopes: string[];
  transport: string | null;
  last_seen_seconds: number;
  capabilities: Array<{ name: string; state: string; detail: Record<string, unknown> }>;
  client: Record<string, string>;
  clock: { offset_ms: number | null };
  stats: Record<string, number>;
};

export type PresenceDevice = {
  id: string;
  name: string;
  device_type: string;
  role: "presence";
  grants: string[];
  credential: "key" | "secret";
  created_at: string;
  last_seen: string;
  revoked: boolean;
  sessions: PresenceSession[];
};

export type PairingCode = { code: string; expires_at: string; scopes: string[]; protocol: string; endpoints: string[] };

async function json<T>(config: BackendConfig, path: string, init: RequestInit = {}): Promise<T> {
  try {
    const response = await apiFetch(config, path, {
      ...init, headers: init.body ? { "Content-Type": "application/json", ...init.headers } : init.headers,
    });
    return await response.json() as T;
  } catch (error) {
    if (error instanceof ApiError) {
      const payload = error.payload ?? {};
      throw new RemoteFailure(String(payload.code ?? error.kind), String(payload.detail ?? error.message), undefined, false, error.status);
    }
    throw error;
  }
}

export function remoteOwnerApi(config: BackendConfig) {
  const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });
  return {
    catalog: () => json<{ scopes: Array<{ scope: string; description: string; requires: string[] }>; presets: Record<string, string[]> }>(config, "/remote/catalog"),
    createPairingCode: (input: { preset?: string; scopes?: string[]; label?: string }) => json<PairingCode>(config, "/remote/pairing-codes", post(input)),
    devices: () => json<{ devices: PresenceDevice[]; owner_sessions: PresenceSession[] }>(config, "/remote/devices"),
    setScopes: (deviceId: string, scopes: string[]) =>
      json<{ device: PresenceDevice }>(config, `/remote/devices/${encodeURIComponent(deviceId)}`, { method: "PATCH", body: JSON.stringify({ scopes }) }),
    revoke: (deviceId: string) => json<{ status: string; sessions_closed: number }>(config, `/remote/devices/${encodeURIComponent(deviceId)}`, { method: "DELETE" }),
    approvals: () => json<{ approvals: Approval[] }>(config, "/remote/approvals"),
    decide: (approvalId: string, approve: boolean) => json<Record<string, unknown>>(config, `/remote/approvals/${encodeURIComponent(approvalId)}`, post({ approve })),
    providers: (capability?: string) => json<Record<string, unknown>>(config, `/remote/providers${capability ? `?capability=${encodeURIComponent(capability)}` : ""}`),
    audit: (after = 0) => json<{ available: boolean; events: Array<Record<string, unknown>> }>(config, `/remote/audit?after=${after}`),
    verifyAudit: () => json<{ verified: boolean; reason?: string }>(config, "/remote/audit/verify", { method: "POST" }),
  };
}

function ownerHttp(config: BackendConfig): HttpRequest {
  return async (path, init) => {
    try {
      const response = await apiFetch(config, path, {
        method: init.method, signal: init.signal,
        ...(init.body !== undefined ? { body: JSON.stringify(init.body), headers: { "Content-Type": "application/json" } } : {}),
      });
      return { status: response.status, json: await response.json().catch(() => ({})) };
    } catch (error) {
      if (error instanceof ApiError && error.status) return { status: error.status, json: error.payload ?? {} };
      throw error;
    }
  };
}

/** The owner's realtime presence in its own Spatial Lab (previews, presence, roster, approvals). */
export function ownerSession(config: BackendConfig, label: string, capabilities: () => CapabilityReport[]): RemoteSessionClient {
  const handshake = () => json<Welcome>(config, "/remote/owner-sessions",
    { method: "POST", body: JSON.stringify({ label, client: { app: "akashi", shell: isDesktopRuntime() ? "desktop" : "web" }, capabilities: capabilities() }) });
  const transports = [
    ...(!isDesktopRuntime() && typeof WebSocket !== "undefined" && config.baseUrl
      ? [{ name: "websocket" as const, create: (events: ConstructorParameters<typeof WebSocketTransport>[1]) => new WebSocketTransport(config.baseUrl, events) }]
      : []),
    { name: "http" as const, create: (events: ConstructorParameters<typeof HttpTransport>[1]) => new HttpTransport(ownerHttp(config), events) },
  ];
  return new RemoteSessionClient({ handshake, transports });
}
