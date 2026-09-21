import assert from "node:assert/strict";
import { test } from "node:test";

process.env.NODE_ENV = "production";
process.env.NEXT_PUBLIC_AKASHI_ALLOW_HTTP = "0";
const { normalizeBackendUrl, apiUrl, apiFetch, fetchProtectedImage, getEditProgress, loadBackendConfig, saveBackendConfig, ApiError } = await import("../src/lib/api.ts");
const config = { baseUrl: "https://api.example.com", token: "test-token" };

test("normalizes trailing slashes and resolves backend-owned paths", () => {
  assert.equal(normalizeBackendUrl("  https://api.example.com///  "), "https://api.example.com");
  assert.equal(apiUrl(config, "/image/view?filename=x.png"), "https://api.example.com/image/view?filename=x.png");
});

test("rejects HTTP production URLs and credential or path injection", () => {
  for (const input of ["http://192.168.1.4:8000", "https://user:secret@api.example.com", "https://api.example.com/api"]) {
    assert.throws(() => normalizeBackendUrl(input), ApiError);
  }
  assert.throws(() => apiUrl(config, "//evil.example.com"), ApiError);
});

test("sends the bearer token as a header, never in the URL", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    assert.equal(url, "https://api.example.com/chat");
    assert.equal(new Headers(init.headers).get("Authorization"), "Bearer test-token");
    return new Response("{}", { status: 200 });
  };
  try {
    assert.equal((await apiFetch(config, "/chat")).status, 200);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("distinguishes authentication, image, and network failures", async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response("", { status: 401 });
    await assert.rejects(apiFetch(config, "/chat"), (error) => error.kind === "auth");
    globalThis.fetch = async () => new Response("", { status: 502 });
    await assert.rejects(apiFetch(config, "/image/view?filename=x"), (error) => error.kind === "image");
    globalThis.fetch = async () => { throw new Error("offline"); };
    await assert.rejects(apiFetch(config, "/chat"), (error) => error.kind === "unavailable");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("service failures are not connectivity failures and redirects are disabled", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async (_url, init) => { assert.equal(init.redirect, "error"); return new Response(JSON.stringify({ detail: "Research provider returned 403." }), { status: 502 }); };
  try { await assert.rejects(apiFetch(config, "/research"), (error) => error.kind === "service" && error.message.includes("403")); }
  finally { globalThis.fetch = original; }
});

test("loads a protected image through FastAPI with a header, not a tokenized URL", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    assert.equal(url, "https://api.example.com/image/view?filename=x.png");
    assert.equal(new Headers(init.headers).get("Authorization"), "Bearer test-token");
    return new Response(new Uint8Array([137, 80, 78, 71]), { status: 200, headers: { "Content-Type": "image/png" } });
  };
  try {
    const blobUrl = await fetchProtectedImage(config, "/image/view?filename=x.png");
    assert.ok(blobUrl.startsWith("blob:"));
    URL.revokeObjectURL(blobUrl);
    await assert.rejects(fetchProtectedImage(config, "https://comfy.example/view"), (error) => error.kind === "image");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("polls authenticated image-edit progress without exposing the token", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    assert.equal(url, "https://api.example.com/image/edit/status/request-id");
    assert.equal(new Headers(init.headers).get("Authorization"), "Bearer test-token");
    assert.equal(String(url).includes("test-token"), false);
    return Response.json({ stage: "editing", profile: "fast" });
  };
  try {
    assert.deepEqual(await getEditProgress(config, "request-id"), { stage: "editing", profile: "fast" });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("web keeps the URL across sessions but not the token in localStorage", async () => {
  const local = new Map();
  const session = new Map();
  const storage = (map) => ({
    getItem: (key) => map.get(key) || null,
    setItem: (key, value) => map.set(key, value),
    removeItem: (key) => map.delete(key),
  });
  globalThis.localStorage = storage(local);
  globalThis.sessionStorage = storage(session);
  const saved = await saveBackendConfig({ baseUrl: "https://api.example.com///", token: "personal-test-token" });
  assert.equal(saved.baseUrl, "https://api.example.com");
  assert.equal(local.get("akashi_backend_url"), "https://api.example.com");
  assert.equal(local.has("akashi_backend_token"), false);
  assert.equal(session.get("akashi_backend_token"), "personal-test-token");
  assert.deepEqual(await loadBackendConfig(), saved);
});
