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
    for (const route of ["/autonomy/tasks", "/expertise/characters", "/expertise/experiences", "/expertise/workshops", "/expertise/workshops/evidence"]) {
      const response = await page.evaluate((path) => window.akashiDesktop.api.fetch({ path, method: "GET", headers: {}, body: { kind: "none" }, authenticated: true }), route);
      assert.equal(response.status, 200, `packaged ${route} failed`);
      assert.ok(JSON.parse(Buffer.from(response.body, "base64").toString("utf8")));
    }
    assert.ok(fs.existsSync(path.join(userData, "runtime", "core", "private", "expertise.sqlite3")));
    console.log("V2_V3_PACKAGED_API_AND_WRITABLE_STORAGE ok");
    async function coreRequest(path, value) {
      const response = await page.evaluate(({ path, value }) => window.akashiDesktop.api.fetch({ path, method: value ? "POST" : "GET",
        headers: value ? { "Content-Type": "application/json" } : {}, body: value ? { kind: "text", value: JSON.stringify(value) } : { kind: "none" }, authenticated: true }), { path, value });
      assert.ok(response.status >= 200 && response.status < 300, `${path}: ${response.status}`);
      return JSON.parse(Buffer.from(response.body, "base64").toString("utf8"));
    }
    const specialistTools = await coreRequest("/tools");
    for (const name of ["character.improve", "character.improvement_status", "character.materialize_blender", "character.refine_blender",
                       "character.train_yourself", "character.training_status", "character.production_recipe", "character.training_control", "character.apply_learned_method",
                       "character.build", "character.production_status", "character.practice_production", "character.production_control"]) {
      assert.equal(specialistTools.tools.filter((tool) => tool.name === name).length, 1, `${name} missing/duplicated in packaged Core`);
    }
    assert.equal(specialistTools.tools.find((tool) => tool.name === "character.refine_blender").risk, "confirm");
    console.log("V31_SPECIALIST_TOOLS_REGISTERED_WITH_APPROVAL_BOUNDARY ok");
    const syntheticAsset = await coreRequest("/expertise/characters", {
      source: { reference: "synthetic:packaged-v31-test", synthetic: true, category: "synthetic_fixture" },
      character: { name: "SYNTHETIC-PACKAGED-WEIGHT-FIXTURE", metadata: { synthetic: true },
        joints: [{ id: "bone", name: "synthetic_bone" }],
        meshes: [{ id: "mesh", name: "synthetic_triangle", vertex_count: 3, positions: [[0,0,0],[1,0,0],[0,1,0]], faces: [[0,1,2]], skin_id: "skin" }],
        skins: [{ id: "skin", mesh_id: "mesh", joints: ["bone"], weights: [{ bone: .3 },{ bone: 1 },{ bone: 1 }] }] },
    });
    const workshop = await coreRequest("/expertise/workshops", { asset_id: syntheticAsset.id });
    const pausedWorkshop = await coreRequest(`/expertise/workshops/${workshop.id}/run?steps=1`, {});
    assert.equal(pausedWorkshop.status, "paused");
    assert.notEqual(pausedWorkshop.best_version, workshop.baseline_version);
    const versionResponse = await coreRequest(`/expertise/versions/${pausedWorkshop.best_version}`);
    assert.equal(versionResponse.evaluation.integrity.defective_vertices, 0);
    assert.equal(versionResponse.evaluation.deformation.available, false); // No invented bind-space/pose data.
    console.log("V31_PACKAGED_IMPROVEMENT_CHECKPOINT_AND_HONEST_EVIDENCE ok");
    const training = await coreRequest("/expertise/training", { max_exercises: 2, candidates_per_exercise: 4 });
    const pausedTraining = await coreRequest(`/expertise/training/${training.id}/run`, {});
    assert.equal(pausedTraining.status, "paused");
    const practice = (await coreRequest(`/expertise/training/${training.id}/exercises`)).exercises[0];
    assert.equal(practice.synthetic, true);
    const bestPractice = await coreRequest(`/expertise/training/${training.id}/artifacts/${practice.id}`);
    assert.equal(bestPractice.metadata.synthetic, true);
    assert.equal((await coreRequest(`/expertise/training/${training.id}/dataset`)).record_count, 0);
    assert.ok((await coreRequest(`/expertise/training/${training.id}/dataset?include_synthetic=true`)).record_count > 0);
    console.log("SELF_TRAINING_PACKAGED_HEADLESS_API_AND_SYNTHETIC_BOUNDARY ok");
    const production = await coreRequest("/expertise/production", { design: { hud: true } });
    const numericProduction = await coreRequest(`/expertise/production/${production.id}/numeric`, {});
    assert.equal(numericProduction.status, "numeric_ready");
    assert.equal(numericProduction.best.evaluation.passed, true);
    assert.equal(numericProduction.best.evaluation.visual_fidelity, "unmeasured");
    const productionBest = await coreRequest(`/expertise/production/${production.id}/best`);
    assert.equal(productionBest.metadata.synthetic, true);
    assert.equal(productionBest.joints.length, 57);
    assert.ok(productionBest.meshes.some(m => m.id === "body-neck"));
    for (const name of ["character.build", "character.practice_production", "character.production_control"]) {
      assert.equal(specialistTools.tools.find(t => t.name === name).risk, "confirm");
    }
    assert.ok(fs.existsSync(path.join(path.dirname(executablePath), "resources", "agent", "akashi_agent", "blender_production.py")));
    console.log("PRODUCTION_PACKAGED_NUMERIC_CORRECTION_AND_FIXED_DCC_RESOURCES ok");

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

    // Synthetic checkpoint fixture; no autonomous/model task is executed here.
    const checkpointPath = path.join(userData, "runtime", "core", "private", "autonomy_tasks.json");
    const checkpoints = JSON.parse(fs.readFileSync(checkpointPath, "utf8"));
    checkpoints.tasks["operator-synthetic-checkpoint"] = {
      id: "operator-synthetic-checkpoint", session_id: "synthetic", goal: "synthetic checkpoint fixture",
      title: "Synthetic restart fixture", status: "running", revision: 0, updated_at: new Date().toISOString(),
      subgoals: [{ id: "done", status: "completed" }, { id: "inflight", status: "running" }],
      artifacts: [], entities: {}, events: [], synthetic: true,
    };
    fs.writeFileSync(checkpointPath, JSON.stringify(checkpoints));
    const beforeRestart = state.components.core.pid;
    await application.evaluate((_electron, pid) => process.kill(pid), beforeRestart);
    state = await waitForValue(() => page.evaluate(() => window.akashiDesktop.runtime.status()),
      (current) => current.components.core.state === "READY" && current.components.core.pid !== beforeRestart,
      "packaged Core checkpoint recovery");
    const checkpointResponse = await page.evaluate(() => window.akashiDesktop.api.fetch({
      path: "/autonomy/tasks/operator-synthetic-checkpoint", method: "GET", headers: {}, body: { kind: "none" }, authenticated: true,
    }));
    assert.equal(checkpointResponse.status, 200);
    const recoveredCheckpoint = JSON.parse(Buffer.from(checkpointResponse.body, "base64").toString("utf8"));
    assert.equal(recoveredCheckpoint.status, "paused_recovery");
    assert.equal(recoveredCheckpoint.subgoals[0].status, "completed");
    assert.equal(recoveredCheckpoint.subgoals[1].status, "pending");
    console.log("V2_SYNTHETIC_CHECKPOINT_SURVIVES_CORE_RESTART ok");
    const recoveredWorkshop = await coreRequest(`/expertise/workshops/${workshop.id}`);
    assert.equal(recoveredWorkshop.best_version, pausedWorkshop.best_version);
    assert.equal(recoveredWorkshop.attempts, 1);
    const durableVersion = await coreRequest(`/expertise/versions/${recoveredWorkshop.best_version}`);
    assert.equal(durableVersion.document.skins[0].weights[0].bone, 1);
    console.log("V31_BEST_VERSION_AND_WEIGHTS_SURVIVE_ACTUAL_CORE_RESTART ok");
    const recoveredTraining = await coreRequest(`/expertise/training/${training.id}`);
    assert.equal(recoveredTraining.status, "paused");
    assert.equal(recoveredTraining.completed_exercises, 1);
    const durablePractice = (await coreRequest(`/expertise/training/${training.id}/exercises`)).exercises[0];
    assert.equal(durablePractice.best_digest, practice.best_digest);
    assert.deepEqual(await coreRequest(`/expertise/training/${training.id}/artifacts/${practice.id}`), bestPractice);
    console.log("SELF_TRAINING_IMMUTABLE_BEST_AND_NO_AUTO_RESUME_AFTER_CORE_RESTART ok");
    const durableProduction = (await coreRequest(`/expertise/production/${production.id}`)).job;
    assert.equal(durableProduction.status, "numeric_ready");
    assert.equal(durableProduction.best.document_digest, numericProduction.best.document_digest);
    assert.deepEqual(await coreRequest(`/expertise/production/${production.id}/best`), productionBest);
    console.log("PRODUCTION_BEST_SURVIVES_CORE_RESTART_WITH_NO_AUTO_DCC_RUN ok");

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
