const { _electron: electron } = require("../../../frontend/node_modules/playwright");
const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");

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

async function launch(executablePath, userData, env) {
  return electron.launch({
    executablePath,
    args: [`--user-data-dir=${userData}`],
    env,
    timeout: 45_000,
  });
}

async function runtimeReady(page) {
  return waitForValue(
    () => page.evaluate(() => window.akashiDesktop?.runtime?.status()),
    (state) => state?.components.core.state === "READY" && state?.components.agent.state === "READY",
    "packaged runtime readiness",
    45_000,
  );
}

function waitForExit(child, timeoutMs = 15_000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("Second instance did not exit.")), timeoutMs);
    child.once("error", reject);
    child.once("exit", (code) => { clearTimeout(timer); resolve(code); });
  });
}

async function waitForValue(operation, predicate, label, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const value = await operation();
    if (predicate(value)) return value;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Timed out waiting for ${label}.`);
}

function processAlive(pid) {
  try { process.kill(pid, 0); return true; } catch { return false; }
}

(async () => {
  const executablePath = path.resolve(__dirname, "../dist/win-unpacked/AKASHİ ABSOLUTE.exe");
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), "akashi-packaged-runtime-"));
  const corePort = await freePort();
  const agentPort = await freePort();
  const env = {
    ...process.env,
    AKASHI_DESKTOP_CORE_MODE: "local",
    AKASHI_DESKTOP_CORE_URL: `http://127.0.0.1:${corePort}`,
    AKASHI_AGENT_PORT: String(agentPort),
    AKASHI_RUNTIME_HEARTBEAT_MS: "750",
    AI_PROVIDER: "mock",
    MISS_MINUTES_ENABLED: "false",
  };
  delete env.ELECTRON_RUN_AS_NODE;
  let application;
  try {
    application = await launch(executablePath, userData, env);
    let page = await application.firstWindow();
    let state = await runtimeReady(page);
    assert.equal(state.components.core.owned, true);
    assert.equal(state.components.agent.owned, true);
    const originalCorePid = state.components.core.pid;
    const originalAgentPid = state.components.agent.pid;
    console.log(`PACKAGED_READY core=${originalCorePid} agent=${originalAgentPid}`);

    const second = spawn(executablePath, [`--user-data-dir=${userData}`], {
      env, windowsHide: true, shell: false, stdio: "ignore",
    });
    const secondCode = await waitForExit(second);
    assert.equal(secondCode, 0);
    state = await page.evaluate(() => window.akashiDesktop.runtime.status());
    assert.equal(state.components.core.pid, originalCorePid);
    assert.equal(state.components.agent.pid, originalAgentPid);
    console.log("SINGLE_INSTANCE_REUSED ok");

    await application.evaluate((_electron, pid) => process.kill(pid), originalAgentPid);
    state = await waitForValue(
      () => page.evaluate(() => window.akashiDesktop.runtime.status()),
      (current) => current.components.agent.state === "READY" &&
        Number.isInteger(current.components.agent.pid) &&
        current.components.agent.restartCount >= 1,
      "packaged Agent recovery",
    );
    assert.ok(state.components.agent.restartCount >= 1);
    const agentHealth = await page.evaluate(() => window.akashiDesktop.agent.status());
    assert.equal(agentHealth.status, "ok");
    console.log(`AGENT_RECOVERED old=${originalAgentPid} new=${state.components.agent.pid}`);

    const owned = [state.components.core.pid, state.components.agent.pid];
    await application.close();
    application = null;
    await new Promise((resolve) => setTimeout(resolve, 1500));
    for (const pid of owned) assert.equal(processAlive(pid), false, `owned PID ${pid} survived shutdown`);
    console.log("OWNED_CHILDREN_STOPPED ok");

    application = await launch(executablePath, userData, env);
    page = await application.firstWindow();
    state = await runtimeReady(page);
    assert.equal(state.components.core.state, "READY");
    assert.equal(state.components.agent.state, "READY");
    console.log("RELAUNCH_RECOVERED ok");
  } finally {
    if (application) await application.close().catch(() => undefined);
    await new Promise((resolve) => setTimeout(resolve, 750));
    const resolved = path.resolve(userData);
    if (resolved.startsWith(path.resolve(os.tmpdir()) + path.sep) && path.basename(resolved).startsWith("akashi-packaged-runtime-")) {
      fs.rmSync(resolved, { recursive: true, force: true });
    }
  }
  console.log("PASS: packaged Electron one-click startup, single-instance focus, Agent recovery, owned cleanup, and relaunch.");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
