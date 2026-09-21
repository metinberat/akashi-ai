import assert from "node:assert/strict";
import { test } from "node:test";

process.env.NODE_ENV = "production";
const calls = [];
globalThis.window = {
  akashiDesktop: {
    platform: "win32",
    config: {
      load: async () => ({ baseUrl: "http://127.0.0.1:8000", tokenStored: true }),
      save: async (value) => ({ baseUrl: value.baseUrl, tokenStored: true }),
    },
    api: {
      fetch: async (request) => {
        calls.push(request);
        return {
          status: 200,
          statusText: "OK",
          headers: { "content-type": "application/json" },
          body: Buffer.from('{"status":"ok"}').toString("base64"),
        };
      },
    },
    shell: { showDataFolder: async () => true, openExternal: async () => true },
  },
};

const { apiFetch, loadBackendConfig, normalizeBackendUrl, saveBackendConfig } = await import("../src/lib/api.ts");

test("desktop accepts private HTTP and keeps the stored token outside renderer config", async () => {
  assert.equal(normalizeBackendUrl("http://127.0.0.1:8000"), "http://127.0.0.1:8000");
  assert.deepEqual(await loadBackendConfig(), {
    baseUrl: "http://127.0.0.1:8000",
    token: "",
    tokenStored: true,
  });
  const saved = await saveBackendConfig({ baseUrl: "https://api.example.com", token: "replacement" });
  assert.equal(saved.token, "");
  assert.equal(saved.tokenStored, true);
});

test("desktop API requests cross the narrow IPC bridge without an Authorization header", async () => {
  const response = await apiFetch(
    { baseUrl: "http://127.0.0.1:8000", token: "", tokenStored: true },
    "/chat",
    { method: "POST", headers: { "Content-Type": "application/json" }, body: '{"message":"hi"}' },
  );
  assert.equal((await response.json()).status, "ok");
  assert.equal(calls[0].path, "/chat");
  assert.equal(calls[0].headers.authorization, undefined);
  assert.equal(calls[0].body.kind, "text");
});
