const { _electron: electron } = require("../../../frontend/node_modules/playwright");
const path = require("node:path");
const fs = require("node:fs");
const assert = require("node:assert/strict");
const root = path.resolve(__dirname, ".."), repo = path.resolve(root, "../..");
let app;
async function main() {
  const report = JSON.parse(fs.readFileSync(path.join(root, ".validation/local-quality-report.json"), "utf8"));
  app = await electron.launch({ executablePath: path.join(root, "dist/win-unpacked/FORM Character Studio.exe"),
    args: [], env: {...process.env, FORM_PYTHON: path.join(repo, "backend/.venv/Scripts/python.exe"),
      FORM_DATA_DIR: path.join(root, ".validation/local-quality"), FORM_EXTERNAL_MODELS_ENABLED: "false"} });
  const page = await app.firstWindow();
  const errors = [];
  page.on("pageerror", e => errors.push(e.message));
  await page.waitForFunction(() => document.querySelector(".project-item"));
  await page.locator(`[data-project="${report.project}"]`).click();
  await page.waitForFunction(() => document.querySelector(".version"));
  const snapshot = await page.evaluate(key => fetch("/api/projects/"+key).then(r=>r.json()), report.project);
  assert(snapshot.project.visual_lab.best);
  const bestIndex = snapshot.runs.findIndex(r => r.id === snapshot.project.visual_lab.best.run_id);
  await page.locator(".version").nth(bestIndex).click();
  await page.setViewportSize({width:1920,height:1080});
  await page.screenshot({path:path.join(root,".validation/quality-1920.png")});
  await page.locator('[data-view="compare"]').click();
  await page.setViewportSize({width:3440,height:1440});
  await page.screenshot({path:path.join(root,".validation/quality-compare-3440.png")});
  await page.locator('[data-view="learning"]').click();
  await page.waitForFunction(() => document.querySelector("#learning").textContent.includes("visual trials"));
  await page.screenshot({path:path.join(root,".validation/quality-learning-3440.png")});
  await page.getByRole("button",{name:"Inspect actual shape in 3D"}).last().click();
  await page.waitForFunction(() => document.getElementById("viewer").dataset.loaded === "true");
  await page.setViewportSize({width:1920,height:1080});
  await page.screenshot({path:path.join(root,".validation/local-shape-1920.png")});
  const art = JSON.parse(fs.readFileSync(path.join(root,".validation/art-reference-report.json"),"utf8"));
  await page.locator(`[data-project="${art.project}"]`).click();
  await page.waitForFunction(() => document.querySelector("#name").textContent.startsWith("AKASHI artwork"));
  await page.getByRole("button",{name:"Inspect actual shape in 3D"}).last().click();
  await page.waitForFunction(() => document.getElementById("viewer").dataset.loaded === "true" && document.querySelector("#notice").textContent.includes("local shape loaded"));
  await page.waitForTimeout(5000); // Must remain visible across the actual polling refresh.
  assert.equal(await page.locator("#viewer").isVisible(),true);
  assert.equal(await page.locator("#empty").isVisible(),false);
  assert.equal(await page.locator("#skeleton").isDisabled(),true);
  await page.screenshot({path:path.join(root,".validation/art-reference-1920.png")});
  await page.setViewportSize({width:3440,height:1440});
  await page.screenshot({path:path.join(root,".validation/art-reference-3440.png")});
  assert.equal(errors.length,0, errors.join("\n"));
  fs.writeFileSync(path.join(root,".validation/quality-ui-report.json"),JSON.stringify({packaged:true, project:report.project,
    real_artifacts:true, learned_shape_loaded:true, user_art_shape_loaded:true, art_project:art.project, js_errors:errors, viewports:["1920x1080","3440x1440"]},null,2));
  const closed = app.waitForEvent("close",{timeout:240000});
  await app.evaluate(({app})=>app.quit());
  await closed;
  app = null;
  console.log("Packaged local-quality / learned-shape UI passed; real artifact screenshots captured.");
}
main().catch(async e=>{console.error(e);if(app)await app.evaluate(({app})=>app.quit());process.exitCode=1;});
