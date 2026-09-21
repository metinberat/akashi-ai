import { Capacitor } from "@capacitor/core";
import { SecureStorage } from "@aparajita/capacitor-secure-storage";

export type BackendConfig = {
  baseUrl: string;
  token: string;
  tokenStored?: boolean;
  coreMode?: "local" | "remote";
};
export type ConnectionState = "connected" | "connecting" | "disconnected" | "auth-failed";
export type ApiErrorKind = "config" | "unavailable" | "auth" | "chat" | "image" | "service" | "cancelled";
export type EditProgress = {
  stage: "preparing" | "editing" | "finalizing" | "completed" | "failed";
  profile: "fast" | "quality";
};

const URL_KEY = "akashi_backend_url";
const TOKEN_KEY = "akashi_backend_token";
const developmentFallback = process.env.NODE_ENV === "development" ? "http://localhost:8000" : "";
const allowHttp = process.env.NODE_ENV === "development" ||
  process.env.NEXT_PUBLIC_AKASHI_ALLOW_HTTP === "1";

export function isDesktopRuntime(): boolean {
  return typeof window !== "undefined" && Boolean(window.akashiDesktop);
}

function isPrivateHost(hostname: string): boolean {
  const host = hostname.replace(/^\[|\]$/gu, "").toLowerCase();
  if (["localhost", "127.0.0.1", "::1"].includes(host)) return true;
  const parts = host.split(".").map(Number);
  if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part) || part < 0 || part > 255)) return false;
  return parts[0] === 10 || parts[0] === 127 ||
    (parts[0] === 192 && parts[1] === 168) ||
    (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31);
}

export class ApiError extends Error {
  constructor(public readonly kind: ApiErrorKind, message: string, public readonly status?: number) {
    super(message);
    this.name = "ApiError";
  }
}

export function normalizeBackendUrl(input: string): string {
  const trimmed = input.trim();
  if (!trimmed) return "";
  let url: URL;
  try {
    url = new URL(trimmed);
  } catch {
    throw new ApiError("config", "Geçerli bir backend adresi gir.");
  }
  if (!url.hostname || url.username || url.password || !/^\/+$/u.test(url.pathname) || url.search || url.hash ||
      !["http:", "https:"].includes(url.protocol)) {
    throw new ApiError("config", "Yalnızca backend kök adresini gir (yol veya kimlik bilgisi olmadan).");
  }
  const desktopHttp = isDesktopRuntime() && isPrivateHost(url.hostname);
  if (url.protocol === "http:" && !allowHttp && !desktopHttp) {
    throw new ApiError("config", "HTTP yalnızca açık Android/LAN geliştirme derlemelerinde kullanılabilir. HTTPS gir.");
  }
  return url.origin;
}

export async function loadBackendConfig(): Promise<BackendConfig> {
  if (isDesktopRuntime()) {
    const stored = await window.akashiDesktop!.config.load();
    return {
      baseUrl: stored.baseUrl,
      token: "",
      tokenStored: stored.tokenStored,
      ...(stored.coreMode ? { coreMode: stored.coreMode } : {}),
    };
  }
  if (Capacitor.isNativePlatform()) {
    const [baseUrl, token] = await Promise.all([
      SecureStorage.getItem(URL_KEY),
      SecureStorage.getItem(TOKEN_KEY),
    ]);
    return { baseUrl: baseUrl || "", token: token || "" };
  }
  // Web development convenience: never persist a bearer token in localStorage.
  return {
    baseUrl: localStorage.getItem(URL_KEY) || developmentFallback,
    token: sessionStorage.getItem(TOKEN_KEY) || "",
  };
}

export async function loadProviderConfig(): Promise<DesktopProviderConfig | null> {
  if (!isDesktopRuntime()) return null;
  return window.akashiDesktop!.provider.load();
}

export async function saveProviderConfig(value: { aiProvider?: string; geminiApiKey?: string; geminiModel?: string }): Promise<DesktopProviderConfig | null> {
  if (!isDesktopRuntime()) return null;
  return window.akashiDesktop!.provider.save(value);
}

export async function saveBackendConfig(config: BackendConfig): Promise<BackendConfig> {
  const normalized = { baseUrl: normalizeBackendUrl(config.baseUrl), token: config.token.trim() };
  if (isDesktopRuntime()) {
    const saved = await window.akashiDesktop!.config.save({
      baseUrl: normalized.baseUrl,
      coreMode: config.coreMode,
      ...(normalized.token ? { token: normalized.token } : {}),
    });
    return {
      baseUrl: saved.baseUrl,
      token: "",
      tokenStored: saved.tokenStored,
      ...(saved.coreMode ? { coreMode: saved.coreMode } : {}),
    };
  }
  if (Capacitor.isNativePlatform()) {
    if (normalized.baseUrl) await SecureStorage.setItem(URL_KEY, normalized.baseUrl);
    else await SecureStorage.removeItem(URL_KEY);
    if (normalized.token) await SecureStorage.setItem(TOKEN_KEY, normalized.token);
    else await SecureStorage.removeItem(TOKEN_KEY);
  } else {
    if (normalized.baseUrl) localStorage.setItem(URL_KEY, normalized.baseUrl);
    else localStorage.removeItem(URL_KEY);
    if (normalized.token) sessionStorage.setItem(TOKEN_KEY, normalized.token);
    else sessionStorage.removeItem(TOKEN_KEY);
  }
  return normalized;
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

function base64ToBytes(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

async function desktopBody(body: BodyInit | null | undefined) {
  if (body == null) return { kind: "none" as const };
  if (typeof body === "string") return { kind: "text" as const, value: body };
  if (body instanceof FormData) {
    const entries: Array<
      | { kind: "text"; name: string; value: string }
      | { kind: "file"; name: string; value: string; filename: string; type: string }
    > = [];
    for (const [name, value] of body.entries()) {
      if (typeof value === "string") entries.push({ kind: "text", name, value });
      else entries.push({
        kind: "file",
        name,
        value: bytesToBase64(new Uint8Array(await value.arrayBuffer())),
        filename: value.name,
        type: value.type,
      });
    }
    return { kind: "form" as const, entries };
  }
  if (body instanceof Blob) {
    return { kind: "base64" as const, value: bytesToBase64(new Uint8Array(await body.arrayBuffer())) };
  }
  if (body instanceof ArrayBuffer) {
    return { kind: "base64" as const, value: bytesToBase64(new Uint8Array(body)) };
  }
  if (ArrayBuffer.isView(body)) {
    return {
      kind: "base64" as const,
      value: bytesToBase64(new Uint8Array(body.buffer, body.byteOffset, body.byteLength)),
    };
  }
  throw new ApiError("config", "Desktop bu istek gövdesini güvenli biçimde iletemiyor.");
}

/** Resolve only backend-owned paths; never expose the token in a URL. */
export function apiUrl(config: BackendConfig, path: string): string {
  if (!config.baseUrl) throw new ApiError("config", "Ayarlar'da backend adresini gir.");
  if (!path.startsWith("/") || path.startsWith("//") || /[\\\r\n\t#]/u.test(path)) {
    throw new ApiError("config", "Backend geçersiz bir API yolu döndürdü.");
  }
  return `${normalizeBackendUrl(config.baseUrl)}${path}`;
}

export async function apiFetch(
  config: BackendConfig,
  path: string,
  init: RequestInit = {},
  authenticated = true,
): Promise<Response> {
  const url = apiUrl(config, path);
  const headers = new Headers(init.headers);
  if (authenticated && config.token && !isDesktopRuntime()) headers.set("Authorization", `Bearer ${config.token}`);
  let response: Response;
  try {
    if (init.signal?.aborted) throw new Error("cancelled");
    if (isDesktopRuntime()) {
      const result = await withAbort(window.akashiDesktop!.api.fetch({
        path,
        method: init.method || "GET",
        headers: Object.fromEntries(headers.entries()),
        body: await desktopBody(init.body),
        authenticated,
      }), init.signal);
      const responseBytes = base64ToBytes(result.body);
      const responseBody = responseBytes.buffer.slice(
        responseBytes.byteOffset,
        responseBytes.byteOffset + responseBytes.byteLength,
      ) as ArrayBuffer;
      response = new Response([204, 205, 304].includes(result.status) ? null : responseBody, {
        status: result.status,
        statusText: result.statusText,
        headers: result.headers,
      });
    } else {
      response = await fetch(url, { ...init, headers, redirect: "error", signal: init.signal || AbortSignal.timeout(path.startsWith("/image/") ? 360_000 : 210_000) });
    }
  } catch {
    if (init.signal?.aborted) throw new ApiError("cancelled", "İstek iptal edildi.");
    throw new ApiError("unavailable", "Backend'e ulaşılamıyor. Adresi ve bağlantıyı kontrol et.");
  }
  if (!response.ok) {
    if (response.status === 401 || response.status === 403 ||
        (path === "/auth/check" && response.status === 503)) {
      throw new ApiError("auth", "Erişim anahtarı eksik, hatalı veya backend'de ayarlanmamış.", response.status);
    }
    const kind: ApiErrorKind = path.startsWith("/image/") ? "image" : path === "/chat" ? "chat" : "service";
    let detail = "";
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail.slice(0, 350);
    } catch { /* Status remains useful if the proxy did not return JSON. */ }
    throw new ApiError(kind, `${kind === "image" ? "Görsel servisi" : kind === "chat" ? "Sohbet modeli" : "Servis"} başarısız (${response.status}).${detail ? ` ${detail}` : " Yeniden dene; sunucu günlüklerini kontrol et."}`, response.status);
  }
  return response;
}

function withAbort<T>(operation: Promise<T>, signal?: AbortSignal | null): Promise<T> {
  if (!signal) return operation;
  return new Promise((resolve, reject) => {
    const abort = () => reject(new Error("cancelled"));
    if (signal.aborted) { reject(new Error("cancelled")); return; }
    signal.addEventListener("abort", abort, { once: true });
    operation.then(resolve, reject).finally(() => signal.removeEventListener("abort", abort));
  });
}

export async function testBackendConnection(config: BackendConfig): Promise<void> {
  const signal = AbortSignal.timeout(12_000);
  await apiFetch(config, "/health", { cache: "no-store", signal }, false);
  await apiFetch(config, "/auth/check", { cache: "no-store", signal });
}

export async function clearBackendToken(config: BackendConfig): Promise<BackendConfig> {
  if (isDesktopRuntime()) {
    const saved = await window.akashiDesktop!.config.save({ baseUrl: config.baseUrl, token: "", coreMode: config.coreMode });
    return {
      baseUrl: saved.baseUrl,
      token: "",
      tokenStored: saved.tokenStored,
      ...(saved.coreMode ? { coreMode: saved.coreMode } : {}),
    };
  }
  return saveBackendConfig({ baseUrl: config.baseUrl, token: "" });
}

export async function fetchProtectedImage(config: BackendConfig, path: string): Promise<string> {
  if (!path.startsWith("/image/view?")) {
    throw new ApiError("image", "Backend beklenmeyen bir görsel yolu döndürdü.");
  }
  const response = await apiFetch(config, path);
  return URL.createObjectURL(await response.blob());
}

export async function getEditProgress(
  config: BackendConfig,
  requestId: string,
  signal?: AbortSignal,
): Promise<EditProgress> {
  const response = await apiFetch(config, `/image/edit/status/${encodeURIComponent(requestId)}`, { signal });
  return response.json() as Promise<EditProgress>;
}
