/* Real UI -> independent runtime -> existing production engine -> installed Blender. */
const {
  _electron: electron,
} = require("../../../frontend/node_modules/playwright");
const path = require("node:path");
const fs = require("node:fs");
const assert = require("node:assert/strict");
const root = path.resolve(__dirname, ".."),
  repo = path.resolve(root, "../..");
const output = path.join(root, ".validation");
fs.mkdirSync(output, { recursive: true });
const data =
  process.env.FORM_TEST_DATA || path.join(output, "physical-project");
const executable =
  process.env.FORM_TEST_EXE || require("../node_modules/electron");
const packaged = !!process.env.FORM_TEST_EXE;
let app;
async function launch() {
  return await electron.launch({
    executablePath: executable,
    args: packaged ? [] : [root],
    env: {
      ...process.env,
      FORM_PYTHON: path.join(repo, "backend/.venv/Scripts/python.exe"),
      FORM_DATA_DIR: data,
    },
  });
}
async function main() {
  app = await launch();
  let page = await app.firstWindow();
  await page.waitForLoadState("domcontentloaded");
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.waitForFunction(() =>
    document.getElementById("health").textContent.includes("BLENDER READY"),
  );
  const health = await page.evaluate(() =>
    fetch("/api/health").then((r) => r.json()),
  );
  assert.equal(health.core_required, false);
  await page.locator("#new-project").click();
  await page
    .locator("#project-name")
    .fill("Synthetic / FORM application validation");
  await page
    .locator("#project-brief")
    .fill(
      "A synthetic slender humanoid with a long coat and character-attached energy rings. Technical validation, not professional reference reconstruction.",
    );
  await page.locator("#project-form button[type=submit]").click();
  await page.locator("#build").waitFor({ state: "visible" });
  await page.waitForFunction(() => !document.getElementById("build").disabled);
  await page.locator("#use-model").uncheck();
  await page
    .locator("#message")
    .fill(
      "Synthetic slender humanoid with a coat. Preserve every version and verify the real export.",
    );
  await page.locator("#send").click();
  await page.waitForFunction(() =>
    document
      .querySelector("#messages")
      .textContent.includes("No model interpretation"),
  );
  await page.locator("#build-type").selectOption("slender");
  await page.locator("#hair").selectOption("long");
  await page.locator("#hud").check();
  await page.locator("#build").click();
  await page.waitForFunction(() => document.querySelector(".version"), null, {
    timeout: 30000,
  });
  // Real safe boundary stop/resume through the same application, not a mocked API.
  await page.locator("#pause").click();
  await page.waitForFunction(
    () => document.getElementById("run-state").textContent.startsWith("PAUSED"),
    null,
    { timeout: 240000 },
  );
  await page.locator("#resume").click();
  await page.waitForFunction(
    () =>
      document
        .getElementById("run-state")
        .textContent.startsWith("COMPLETED PARTIAL"),
    null,
    { timeout: 480000 },
  );
  const project = await page.evaluate(() =>
    localStorage.getItem("form-project"),
  );
  let snapshot = await page.evaluate(
    async (key) => fetch("/api/projects/" + key).then((r) => r.json()),
    project,
  );
  const run = snapshot.runs.at(-1);
  assert.equal(run.status, "completed_partial");
  assert(run.steps.includes("export_readback"));
  assert(snapshot.files.some((f) => f.kind === "glb"));
  assert(run.events.some((event) => event.kind === "candidate_evaluated"));
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.screenshot({ path: path.join(output, "studio-1920.png") });
  await page.locator('[data-view="3d"]').click();
  await page.waitForFunction(
    () => document.getElementById("viewer").dataset.loaded === "true",
    null,
    { timeout: 30000 },
  );
  assert(
    Number(await page.locator("#viewer").getAttribute("data-textures")) >= 2,
    "Exported embedded textures must load in the real viewer, not white placeholders",
  );
  await page.locator("#skeleton").click();
  await page.locator("#motion").click();
  await page.waitForTimeout(700);
  await page.screenshot({ path: path.join(output, "3d-1920.png") });
  await page.locator('[data-tab="inspect"]').click();
  await page
    .getByRole("button", { name: "Keep as project best", exact: true })
    .click();
  await page.waitForFunction(() =>
    document.querySelector(".version").textContent.includes("/ BEST"),
  );
  if (process.env.FORM_TEST_TWO_VERSIONS === "1") {
    await page.locator('[data-tab="intent"]').click();
    await page.locator("#clothing").selectOption("armor");
    await page.locator("#hair").selectOption("short");
    await page.locator("#build").click();
    await page.waitForFunction(
      () => document.querySelectorAll(".version").length === 2,
    );
    await page.waitForFunction(
      () =>
        document
          .getElementById("run-state")
          .textContent.startsWith("COMPLETED PARTIAL"),
      null,
      { timeout: 480000 },
    );
    snapshot = await page.evaluate(
      async (key) => fetch("/api/projects/" + key).then((r) => r.json()),
      project,
    );
    assert.equal(snapshot.runs.length, 2);
    assert.equal(snapshot.project.best_run, run.id);
    assert(snapshot.runs.every((r) => r.status === "completed_partial"));
    await page.locator('[data-view="compare"]').click();
    assert.notEqual(
      await page.locator("#compare-a").inputValue(),
      await page.locator("#compare-b").inputValue(),
    );
    await page.screenshot({ path: path.join(output, "compare-1920.png") });
  }
  await page.locator('[data-view="learning"]').click();
  await page
    .getByRole("button", { name: "Train yourself ↗", exact: true })
    .click();
  await page.waitForFunction(
    () =>
      document
        .getElementById("learning")
        .textContent.includes("COMPLETED · 2/2"),
    null,
    { timeout: 120000 },
  );
  await page.screenshot({ path: path.join(output, "learning-1920.png") });
  const bundle = await page.evaluate(
    (key) =>
      fetch("/api/projects/" + key + "/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      }).then((r) => r.json()),
    project,
  );
  assert.equal(bundle.kind, "export");
  const result = await page.evaluate(
    async ({ key, id }) => {
      const r = await fetch("/api/projects/" + key + "/files/" + id);
      return { status: r.status, bytes: (await r.arrayBuffer()).byteLength };
    },
    { key: project, id: bundle.id },
  );
  assert.equal(result.status, 200);
  assert(result.bytes > 10000);
  // Relaunch the actual application; restored project, best and training receipts must survive.
  let closed = app.waitForEvent("close", { timeout: 240000 });
  await app.evaluate(({ app }) => app.quit());
  await closed;
  app = null;
  app = await launch();
  page = await app.firstWindow();
  await page.waitForFunction(
    () => document.querySelector(".version")?.textContent.includes("/ BEST"),
    null,
    { timeout: 30000 },
  );
  assert.equal(
    await page.evaluate(() => localStorage.getItem("form-project")),
    project,
  );
  await page.setViewportSize({ width: 3440, height: 1440 });
  await page.screenshot({ path: path.join(output, "studio-3440.png") });
  await page.locator('[data-view="compare"]').click();
  await page.screenshot({ path: path.join(output, "compare-3440.png") });
  snapshot = await page.evaluate(
    async (key) => fetch("/api/projects/" + key).then((r) => r.json()),
    project,
  );
  assert.equal(snapshot.project.best_run, run.id);
  assert.equal(snapshot.training[0].status, "completed");
  assert.equal(errors.length, 0, errors.join("\n"));
  fs.writeFileSync(
    path.join(output, "app-smoke-report.json"),
    JSON.stringify(
      {
        packaged,
        project,
        run: run.id,
        steps: run.steps,
        technical_status: run.status,
        files: snapshot.files.map((f) => ({ kind: f.kind, bytes: f.bytes })),
        training: snapshot.training.map((r) => ({
          id: r.id,
          status: r.status,
          completed: r.completed_exercises,
        })),
        pause_resume: true,
        relaunch_persistence: true,
        export: result,
        js_errors: errors,
        synthetic: true,
        professional_quality_validated: false,
      },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify({
      status: "passed",
      packaged,
      project,
      run: run.id,
      export_bytes: result.bytes,
      screenshots: output,
    }),
  );
  closed = app.waitForEvent("close", { timeout: 240000 });
  await app.evaluate(({ app }) => app.quit());
  await closed;
  app = null;
}
main().catch(async (e) => {
  console.error(e);
  if (app) {
    try {
      const p = await app.firstWindow();
      await p.screenshot({ path: path.join(output, "failure.png") });
      await app.evaluate(({ app }) => app.quit());
    } catch {}
  }
  process.exitCode = 1;
});
