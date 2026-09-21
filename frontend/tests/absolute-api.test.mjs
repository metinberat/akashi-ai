import assert from "node:assert/strict";
import { test } from "node:test";

process.env.NODE_ENV = "production";
const { createMemory, createTask, queueDeviceAction, discoverIntelligence, startVoiceSession, updateVoiceSession } = await import("../src/lib/absolute-api.ts");
const config = { baseUrl: "https://api.example.com", token: "test-token" };

test("ABSOLUTE services use protected FastAPI routes and structured JSON", async () => {
  const originalFetch = globalThis.fetch;
  const seen = [];
  globalThis.fetch = async (url, init) => {
    seen.push({ url, init });
    return new Response(JSON.stringify({ id: "1", status: "queued" }), {
      status: url.endsWith("/memory") ? 201 : 202,
      headers: { "Content-Type": "application/json" },
    });
  };
  try {
    await createMemory(config, { content: "Concise answers", category: "preference", tags: [] });
    await createTask(config, { title: "Research", approved: false, steps: [{ tool: "research.web", arguments: { question: "x" } }] });
    await queueDeviceAction(config, "device-id", "get_system_status", {}, false);
    assert.deepEqual(seen.map((item) => item.url), [
      "https://api.example.com/memory",
      "https://api.example.com/tasks",
      "https://api.example.com/devices/device-id/actions",
    ]);
    for (const item of seen) {
      assert.equal(new Headers(item.init.headers).get("Authorization"), "Bearer test-token");
      assert.equal(item.init.method, "POST");
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("voice and intelligence remain protected Core routes", async () => {
  const originalFetch = globalThis.fetch;
  const seen = [];
  globalThis.fetch = async (url, init) => {
    seen.push({ url, init });
    return Response.json({ id: "voice-session", state: "listening" });
  };
  try {
    await discoverIntelligence(config);
    await startVoiceSession(config, "conversation", "tr");
    await updateVoiceSession(config, "voice-session", { state: "thinking", interaction_id: "interaction-1" });
    assert.deepEqual(seen.map((item) => item.url), [
      "https://api.example.com/intelligence/discover",
      "https://api.example.com/voice/sessions",
      "https://api.example.com/voice/sessions/voice-session",
    ]);
    assert.deepEqual(seen.map((item) => item.init.method), ["POST", "POST", "PATCH"]);
    for (const item of seen) assert.equal(new Headers(item.init.headers).get("Authorization"), "Bearer test-token");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
