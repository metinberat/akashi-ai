const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");

const { DesktopRuntimeSupervisor } = require("../runtime-supervisor.cjs");

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => resolve(address.port));
    });
  });
}

async function waitFor(predicate, label, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const value = await predicate();
    if (value) return value;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Timed out waiting for ${label}.`);
}

async function api(baseUrl, token, route, options = {}) {
  const response = await fetch(`${baseUrl}${route}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    signal: AbortSignal.timeout(15_000),
  });
  const body = response.status === 204 ? null : await response.json();
  if (!response.ok) throw new Error(`${route} failed (${response.status}): ${JSON.stringify(body)}`);
  return body;
}

(async () => {
  const corePort = await freePort();
  const agentPort = await freePort();
  process.env.AKASHI_AGENT_PORT = String(agentPort);
  process.env.AKASHI_RUNTIME_HEARTBEAT_MS = "750";
  process.env.AKASHI_RUNTIME_STARTUP_TIMEOUT_MS = "15000";
  process.env.AI_PROVIDER = "mock";
  process.env.MISS_MINUTES_ENABLED = "false";

  const userData = fs.mkdtempSync(path.join(os.tmpdir(), "akashi-runtime-integration-"));
  const token = crypto.randomBytes(36).toString("base64url");
  const agentToken = crypto.randomBytes(36).toString("base64url");
  const baseUrl = `http://127.0.0.1:${corePort}`;
  const resourcesFlag = process.argv.indexOf("--resources");
  const resourcesPath = resourcesFlag >= 0 ? path.resolve(process.argv[resourcesFlag + 1]) : userData;
  const isPackaged = resourcesFlag >= 0;
  const options = {
    userData,
    resourcesPath,
    appDirectory: path.resolve(__dirname, ".."),
    isPackaged,
    getConnectionConfig: () => ({ coreMode: "local", baseUrl, token }),
    getAgentToken: () => agentToken,
    probeVoice: async () => ({ ok: true }),
  };
  const supervisor = new DesktopRuntimeSupervisor(options);
  try {
    await supervisor.start();
    let state = supervisor.status();
    assert.equal(state.components.core.state, "READY", JSON.stringify(state.components.core));
    assert.equal(state.components.agent.state, "READY", JSON.stringify(state.components.agent));
    assert.equal(state.components.core.owned, true);
    assert.equal(state.components.agent.owned, true);
    console.log(`READY core=${state.components.core.pid} agent=${state.components.agent.pid}`);

    const completedId = `runtime-completed-${Date.now()}`;
    await api(baseUrl, token, "/chat", {
      method: "POST",
      body: JSON.stringify({ message: "Merhaba", session_id: "runtime-check", interaction_id: completedId }),
    });
    const voice = await api(baseUrl, token, "/voice/sessions", {
      method: "POST", body: JSON.stringify({ session_id: "runtime-voice", language: "tr" }),
    });
    await api(baseUrl, token, `/voice/sessions/${voice.id}`, {
      method: "PATCH",
      body: JSON.stringify({ state: "transcribing", last_user_utterance: "must not persist" }),
    });

    const firstCorePid = state.components.core.pid;
    process.kill(firstCorePid);
    state = await waitFor(() => {
      const current = supervisor.status();
      return current.components.core.state === "READY" && current.components.core.pid !== firstCorePid ? current : null;
    }, "Core recovery");
    const persisted = await api(baseUrl, token, `/live/interactions/${completedId}`);
    assert.equal(persisted.status, "completed");
    const interruptedVoice = await api(baseUrl, token, `/voice/sessions/${voice.id}`);
    assert.equal(interruptedVoice.state, "interrupted");
    assert.equal(interruptedVoice.last_user_utterance, null);
    console.log(`CORE_RECOVERED old=${firstCorePid} new=${state.components.core.pid}`);

    const observer = new DesktopRuntimeSupervisor({ ...options, userData: `${userData}-observer` });
    await observer.start();
    const observerState = observer.status();
    assert.equal(observerState.components.core.owned, false);
    assert.equal(observerState.components.agent.owned, false);
    await observer.stop();
    assert.equal((await api(baseUrl, token, "/auth/check")).status, "ok");
    console.log("REUSE_NO_DUPLICATE ok");

    for (let attempt = 1; attempt <= 3; attempt += 1) {
      const before = supervisor.status().components.agent.pid;
      assert.ok(before);
      process.kill(before);
      if (attempt < 3) {
        await waitFor(() => {
          const current = supervisor.status().components.agent;
          return current.state === "READY" && current.pid !== before ? current : null;
        }, `Agent recovery ${attempt}`);
      } else {
        await waitFor(() => supervisor.status().components.agent.state === "FAILED", "Agent crash-loop cutoff");
      }
    }
    assert.equal(supervisor.status().components.agent.restartCount, 3);
    console.log("CRASH_LOOP_BLOCKED restartCount=3");
  } finally {
    await supervisor.stop();
    await waitFor(async () => {
      try { await fetch(`${baseUrl}/health`, { signal: AbortSignal.timeout(300) }); return false; }
      catch { return true; }
    }, "owned Core shutdown", 10_000).catch(() => undefined);
    fs.rmSync(userData, { recursive: true, force: true });
    fs.rmSync(`${userData}-observer`, { recursive: true, force: true });
  }
  console.log(`PASS: ${isPackaged ? "packaged" : "source"} runtime ownership, recovery, persistence, duplicate reuse, crash-loop protection, and cleanup.`);
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
