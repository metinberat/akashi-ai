/* Short real application inspection of prior generated artifacts; optional live AI. */
const {
  _electron: electron,
} = require("../../../frontend/node_modules/playwright");
const path = require("node:path"),
  fs = require("node:fs"),
  assert = require("node:assert/strict");
const root = path.resolve(__dirname, ".."),
  repo = path.resolve(root, "../.."),
  data =
    process.env.FORM_TEST_DATA ||
    path.join(root, ".validation/physical-project");
async function main() {
  const app = await electron.launch({
    executablePath:
      process.env.FORM_TEST_EXE || require("../node_modules/electron"),
    args: process.env.FORM_TEST_EXE ? [] : [root],
    env: {
      ...process.env,
      FORM_PYTHON: path.join(repo, "backend/.venv/Scripts/python.exe"),
      FORM_DATA_DIR: data,
    },
  });
  try {
    const page = await app.firstWindow(),
      consoleErrors = [];
    page.on("console", (m) => {
      if (m.type() === "error") consoleErrors.push(m.text());
    });
    await page.waitForFunction(() => document.querySelector(".version"));
    await page.locator('[data-view="3d"]').click();
    await page.waitForFunction(
      () => document.getElementById("viewer").dataset.loaded === "true",
    );
    const textures = Number(
      await page.locator("#viewer").getAttribute("data-textures"),
    );
    assert(textures >= 2, "Embedded material textures missing");
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.screenshot({
      path: path.join(root, ".validation/inspection-3d.png"),
    });
    let snapshot = await page.evaluate(async () => {
      const k = localStorage.getItem("form-project");
      return await fetch("/api/projects/" + k).then((r) => r.json());
    });
    const project = snapshot.project.id,
      dir = path.join(data, "projects", project, "outputs");
    const glb = fs.readdirSync(dir).find((f) => f.endsWith(".glb")),
      reference = fs.readdirSync(dir).find((f) => f.endsWith("-front.png"));
    await page.locator("#synthetic").check();
    await page.locator("#upload").setInputFiles(path.join(dir, glb));
    await page.waitForFunction(() =>
      document.getElementById("references").textContent.includes(".glb"),
    );
    await page.locator('[data-tab="inspect"]').click();
    await page.waitForFunction(() =>
      document.getElementById("inspector").textContent.includes("57 joints"),
    );
    await page.locator('[data-tab="intent"]').click();
    await page.locator("#upload").setInputFiles(path.join(dir, reference));
    await page.waitForFunction(() => document.querySelector("#references img"));
    let modelStatus = "not_tested";
    if (process.env.FORM_TEST_AI === "1") {
      await page.locator("#use-model").check();
      await page
        .locator("#message")
        .fill(
          "Propose a supported slender humanoid with a short hairstyle, a coat, and chest-attached energy rings based on this synthetic reference. Keep all colors normalized. Do not claim reconstruction or execute production.",
        );
      await page.locator("#send").click();
      await page.waitForFunction(
        () => !document.getElementById("send").disabled,
        null,
        { timeout: 100000 },
      );
      snapshot = await page.evaluate(
        async (k) => fetch("/api/projects/" + k).then((r) => r.json()),
        project,
      );
      modelStatus = snapshot.messages.at(-1).evidence.model_status;
      assert.equal(
        modelStatus,
        "interpreted",
        JSON.stringify(snapshot.messages.at(-1).evidence),
      );
      assert.equal(snapshot.runs.length, 1, "Model must not execute a build");
      const design = JSON.stringify(snapshot.project.design),
        brief = snapshot.project.brief;
      await page
        .locator("#message")
        .fill(
          "Inspect the actual results in this project. What has passed and what is still unproven? This is a factual question, not a design change.",
        );
      await page.locator("#send").click();
      await page.waitForFunction(
        () => !document.getElementById("send").disabled,
        null,
        { timeout: 100000 },
      );
      snapshot = await page.evaluate(
        async (k) => fetch("/api/projects/" + k).then((r) => r.json()),
        project,
      );
      assert.equal(
        snapshot.messages.at(-1).evidence.model_status,
        "interpreted",
      );
      assert.equal(JSON.stringify(snapshot.project.design), design);
      assert.equal(snapshot.project.brief, brief);
      assert.equal(snapshot.runs.length, 1);
    }
    snapshot = await page.evaluate(
      async (k) => fetch("/api/projects/" + k).then((r) => r.json()),
      project,
    );
    const asset = snapshot.assets.at(-1);
    assert(asset.source.synthetic);
    assert.equal(asset.analysis.observed.joint_count, 57);
    assert.equal(consoleErrors.length, 0, consoleErrors.join("\n"));
    fs.writeFileSync(
      path.join(root, ".validation/inspection-report.json"),
      JSON.stringify(
        {
          textures,
          imported_joints: 57,
          synthetic: true,
          reference_upload: true,
          model_status: modelStatus,
          console_errors: consoleErrors,
          automatic_execution: false,
        },
        null,
        2,
      ),
    );
    console.log(
      JSON.stringify({
        textures,
        modelStatus,
        imported_joints: 57,
        console_errors: consoleErrors,
      }),
    );
  } finally {
    const closed = app.waitForEvent("close", { timeout: 240000 });
    await app.evaluate(({ app }) => app.quit());
    await closed;
  }
}
main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
