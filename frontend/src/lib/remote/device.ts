// Remote presence device: pairing, handshake and transports for a thin client.
// This module never sees AKASHI's API token: a paired device holds only its own
// key (or, in an insecure context, a weaker device secret) and short-lived
// session credentials.

import {
  createDeviceKeys, defaultVault, publicJwk, signProof, subtleAvailable,
  type DeviceCredential, type IdentityVault, type StoredIdentity,
} from "./identity.ts";
import { RemoteFailure, type CapabilityReport, type Welcome } from "./protocol.ts";
import { RemoteSessionClient, type ClientClock } from "./session.ts";
import { HttpTransport, WebSocketTransport, type HttpRequest } from "./transport.ts";

export type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

export function normalizeCoreUrl(input: string): string {
  const url = new URL(input.trim());
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash || !/^\/*$/u.test(url.pathname)) {
    throw new RemoteFailure("bad_url", "Enter only the AKASHI Core address, e.g. https://akashi.example:8443");
  }
  return url.origin;
}

async function call<T>(fetcher: Fetch, coreUrl: string, path: string, body: unknown, timeoutMs = 10_000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetcher(`${coreUrl}${path}`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body), signal: controller.signal, cache: "no-store" });
  } catch (error) {
    throw new RemoteFailure("network", `AKASHI Core is unreachable (${error instanceof Error ? error.message : "network error"}).`, undefined, true);
  } finally {
    clearTimeout(timer);
  }
  const payload = await response.json().catch(() => ({})) as Record<string, unknown>;
  if (!response.ok) {
    throw new RemoteFailure(String(payload.code ?? `http_${response.status}`), String(payload.detail ?? response.statusText),
      payload.details as Record<string, unknown> | undefined, response.status === 429 || response.status >= 500, response.status);
  }
  return payload as T;
}

export type PairInput = { coreUrl: string; code: string; name: string; deviceType: string };

/** Pair once with a code from the owner. Generates the device key on this device. */
export async function pairDevice(input: PairInput, options: { fetcher?: Fetch; vault?: IdentityVault; subtle?: SubtleCrypto } = {}): Promise<StoredIdentity> {
  const fetcher = options.fetcher ?? fetch.bind(globalThis);
  const vault = options.vault ?? defaultVault();
  const coreUrl = normalizeCoreUrl(input.coreUrl);
  const useKey = options.subtle !== undefined || subtleAvailable();
  const keys = useKey ? await createDeviceKeys(options.subtle) : undefined;
  const result = await call<{ device: { id: string; grants: string[] }; device_secret?: string; endpoints: string[] }>(fetcher, coreUrl, "/remote/pair", {
    code: input.code.trim().toUpperCase(), name: input.name.trim(), device_type: input.deviceType,
    public_key: keys ? await publicJwk(keys, options.subtle) : null,
  });
  const credential: DeviceCredential = {
    coreUrl, deviceId: result.device.id, deviceName: input.name.trim(), deviceType: input.deviceType,
    credential: keys ? "key" : "secret", scopes: result.device.grants, pairedAt: new Date().toISOString(),
    endpoints: result.endpoints, ...(result.device_secret ? { secret: result.device_secret } : {}),
  };
  const identity: StoredIdentity = { credential, ...(keys ? { keys } : {}) };
  await vault.save(identity);
  return identity;
}

export type HandshakeInput = {
  identity: StoredIdentity;
  capabilities: () => CapabilityReport[];
  client: Record<string, string>;
  scopes?: string[] | null;
  transport?: string;
};

export async function handshake(input: HandshakeInput, options: { fetcher?: Fetch; subtle?: SubtleCrypto } = {}): Promise<Welcome> {
  const fetcher = options.fetcher ?? fetch.bind(globalThis);
  const { credential, keys } = input.identity;
  const scopes = input.scopes ?? null;
  const body: Record<string, unknown> = { device_id: credential.deviceId, scopes, client: input.client,
    capabilities: input.capabilities(), transport: input.transport };
  if (credential.credential === "key") {
    if (!keys) throw new RemoteFailure("unpaired", "The device key is missing. Pair this device again.");
    const { nonce } = await call<{ nonce: string }>(fetcher, credential.coreUrl, "/remote/challenge", { device_id: credential.deviceId });
    body.nonce = nonce;
    body.signature = await signProof(keys, credential.deviceId, nonce, scopes, options.subtle);
  } else {
    body.secret = credential.secret;
  }
  return call<Welcome>(fetcher, credential.coreUrl, "/remote/sessions", body);
}

export function sessionHttp(coreUrl: string, token: () => string | null, fetcher: Fetch = fetch.bind(globalThis)): HttpRequest {
  return async (path, init) => {
    const response = await fetcher(`${coreUrl}${path}`, {
      method: init.method, signal: init.signal, cache: "no-store",
      headers: { Authorization: `Bearer ${token() ?? ""}`, ...(init.body !== undefined ? { "Content-Type": "application/json" } : {}) },
      ...(init.body !== undefined ? { body: JSON.stringify(init.body) } : {}),
    });
    return { status: response.status, json: await response.json().catch(() => ({})) };
  };
}

export type DeviceSessionOptions = {
  identity: StoredIdentity;
  capabilities: () => CapabilityReport[];
  client: Record<string, string>;
  preferWebSocket?: boolean;
  fetcher?: Fetch;
  clock?: ClientClock;
};

/** A self-healing session for a paired device: WebSocket first, HTTP long-poll fallback. */
export function deviceSession(options: DeviceSessionOptions): RemoteSessionClient {
  const coreUrl = options.identity.credential.coreUrl;
  let client: RemoteSessionClient | null = null;
  const token = () => client?.welcome?.session_token ?? null;
  client = new RemoteSessionClient({
    clock: options.clock,
    handshake: () => handshake({ identity: options.identity, capabilities: options.capabilities, client: options.client }, { fetcher: options.fetcher }),
    transports: [
      ...(options.preferWebSocket !== false && typeof WebSocket !== "undefined"
        ? [{ name: "websocket" as const, create: (events: ConstructorParameters<typeof WebSocketTransport>[1]) => new WebSocketTransport(coreUrl, events) }]
        : []),
      { name: "http" as const, create: (events) => new HttpTransport(sessionHttp(coreUrl, token, options.fetcher), events) },
    ],
  });
  return client;
}
