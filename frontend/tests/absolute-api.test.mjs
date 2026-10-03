import assert from "node:assert/strict";
import { test } from "node:test";

process.env.NODE_ENV = "production";
const { createMemory, createTask, queueDeviceAction, discoverIntelligence, startVoiceSession, updateVoiceSession, listAutonomyTasks, resumeAutonomyTask, getCharacterExpertise, queryCharacterKnowledge,
  createCharacterImprovement, runCharacterImprovement, rollbackCharacterImprovement, cancelCharacterImprovement, getCharacterVersions } = await import("../src/lib/absolute-api.ts");
const config = { baseUrl: "https://api.example.com", token: "test-token" };

test("character workshop remains behind authenticated Core with checkpoint and rollback IDs only", async () => {
  const previous = globalThis.fetch; const seen = [];
  globalThis.fetch = async (url, init) => { seen.push({ url, init }); return Response.json({ id: "improvement-1", status: "paused" }); };
  try {
    await createCharacterImprovement(config, "character-1");
    await runCharacterImprovement(config, "improvement-1");
    await getCharacterVersions(config, "improvement-1");
    await rollbackCharacterImprovement(config, "improvement-1", "version-source");
    await cancelCharacterImprovement(config, "improvement-1");
    assert.deepEqual(seen.map(item => item.url), ["https://api.example.com/expertise/workshops", "https://api.example.com/expertise/workshops/improvement-1/run?steps=2",
      "https://api.example.com/expertise/workshops/improvement-1/versions", "https://api.example.com/expertise/workshops/improvement-1/rollback", "https://api.example.com/expertise/workshops/improvement-1/cancel"]);
    assert.deepEqual(JSON.parse(seen[3].init.body), { version_id: "version-source" });
    for (const item of seen) assert.equal(new Headers(item.init.headers).get("Authorization"), "Bearer test-token");
  } finally { globalThis.fetch = previous; }
});

test("character expertise is queried through protected Core without asset paths", async () => {
  const originalFetch = globalThis.fetch;
  const seen = [];
  globalThis.fetch = async (url, init) => { seen.push({ url, init }); return Response.json({ characters: [], knowledge: [] }); };
  try {
    await getCharacterExpertise(config);
    await queryCharacterKnowledge(config, "forearm twist");
    assert.deepEqual(seen.map((item) => item.url), ["https://api.example.com/expertise/characters?limit=20", "https://api.example.com/expertise/knowledge?query=forearm%20twist&limit=6"]);
    for (const item of seen) assert.equal(new Headers(item.init.headers).get("Authorization"), "Bearer test-token");
  } finally { globalThis.fetch = originalFetch; }
});

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

test("autonomy tasks use authenticated Core checkpoints", async () => {
  const originalFetch = globalThis.fetch;
  const seen = [];
  globalThis.fetch = async (url, init) => {
    seen.push({ url, init });
    return Response.json(url.includes("?limit=") ? { tasks: [] } : { id: "operator-1", status: "queued" });
  };
  try {
    await listAutonomyTasks(config);
    await resumeAutonomyTask(config, "operator-1");
    assert.deepEqual(seen.map((item) => item.url), [
      "https://api.example.com/autonomy/tasks?limit=30",
      "https://api.example.com/autonomy/tasks/operator-1/resume",
    ]);
    assert.equal(seen[1].init.method, "POST");
    for (const item of seen) assert.equal(new Headers(item.init.headers).get("Authorization"), "Bearer test-token");
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
