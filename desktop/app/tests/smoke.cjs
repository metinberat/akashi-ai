const { _electron: electron } = require("../../../frontend/node_modules/playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const net = require("node:net");

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer(); server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const port = server.address().port;
      server.close(() => resolve(port));
    });
  });
}

(async () => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "akashi-desktop-smoke-"));
  const env = { ...process.env, AKASHI_DESKTOP_CORE_MODE: "local",
    AKASHI_DESKTOP_CORE_URL: `http://127.0.0.1:${await freePort()}`,
    AKASHI_AGENT_PORT: String(await freePort()), MISS_MINUTES_ENABLED: "false" };
  delete env.ELECTRON_RUN_AS_NODE;
  const application = await electron.launch({
    executablePath: path.resolve(__dirname, "../dist/win-unpacked/AKASHİ ABSOLUTE.exe"),
    args: [`--user-data-dir=${temporary}`], env, timeout: 45000,
  });
  const visualDirectory = path.resolve(__dirname, "../dist/visual-smoke");
  fs.mkdirSync(visualDirectory, { recursive: true });
  const report = { packaged: true, sizes: [], errors: [], screenshots: [], research: null };
  try {
    const page = await application.firstWindow();
    page.setDefaultTimeout(10000);
    page.on("pageerror", error => report.errors.push(error.message));
    await page.locator(".desktop-command-center").waitFor();
    if (await page.getByRole("button", { name: "Ayarları kapat" }).isVisible()) await page.getByRole("button", { name: "Ayarları kapat" }).click();
    const readyDeadline = Date.now() + 60000;
    while (Date.now() < readyDeadline) {
      report.runtime = await page.evaluate(() => window.akashiDesktop.runtime.status());
      if (report.runtime?.components.core.state === "READY" && report.runtime?.components.agent.state === "READY") break;
      await page.waitForTimeout(500);
    }
    assert.equal(report.runtime?.components.core.state, "READY");
    assert.equal(report.runtime?.components.agent.state, "READY");
    await page.locator('.character-scene[data-renderer="ready"]').waitFor();
    assert.equal(await page.locator(".sidebar").count(), 0);
    const prefs = await application.evaluate(({ BrowserWindow }) => {
      const p = BrowserWindow.getAllWindows()[0].webContents.getLastWebPreferences();
      return { sandbox: p.sandbox, contextIsolation: p.contextIsolation, nodeIntegration: p.nodeIntegration };
    });
    assert.deepEqual(prefs, { sandbox: true, contextIsolation: true, nodeIntegration: false });
    assert.equal(await page.evaluate(() => typeof window.require), "undefined");

    async function resize(width, height) {
      await application.evaluate(({ BrowserWindow }, size) => {
        const win = BrowserWindow.getAllWindows()[0];
        if (win.isMaximized()) win.unmaximize();
        win.setContentSize(size.width, size.height);
      }, { width, height });
      await page.setViewportSize({ width, height });
      await page.waitForTimeout(350);
      const dimensions = await page.evaluate(() => ({ width: innerWidth, height: innerHeight, overflow: document.documentElement.scrollWidth > innerWidth }));
      assert.equal(dimensions.width, width); assert.equal(dimensions.height, height); assert.equal(dimensions.overflow, false);
      report.sizes.push(dimensions);
    }
    async function capture(name) {
      await page.screenshot({ path: path.join(visualDirectory, name + ".png") });
      report.screenshots.push(name + ".png");
    }
    async function energy() { return Number(await page.locator(".character-canvas").getAttribute("data-energy")); }

    await resize(1920, 1080);
    await page.getByRole("button", { name: "CALM", exact: true }).click();
    await page.waitForTimeout(4600);
    const calm = await energy();
    await capture("ambient-calm-1920x1080");
    await page.getByRole("button", { name: "BEST OF BEST", exact: true }).click();
    await page.waitForTimeout(5600);
    const best = await energy();
    await capture("ambient-best-of-best-1920x1080");
    await page.getByRole("button", { name: "HARDCARRY", exact: true }).click();
    const start = await energy(); await capture("ambient-hardcarry-start-1920x1080");
    await page.waitForTimeout(2400);
    const middle = await energy(); await capture("ambient-hardcarry-mid-1920x1080");
    await page.waitForTimeout(3400);
    const end = await energy(); await capture("ambient-hardcarry-full-1920x1080");
    assert.ok(calm < best && start < middle && middle < end && end > .97);
    report.energy = { calm, best, start, middle, end };

    await page.getByRole("button", { name: "BEST OF BEST", exact: true }).click();
    await page.waitForTimeout(5600);
    for (const [width, height] of [[1440,900], [1920,1080], [2560,1440], [3440,1440]]) {
      await resize(width, height);
      await capture(`core-${width}x${height}`);
    }
    report.frameTiming = await page.evaluate(() => new Promise(resolve => {
      const intervals = []; let last = performance.now();
      function tick(now) { intervals.push(now-last); last=now; if(intervals.length<120) requestAnimationFrame(tick); else { const sorted=intervals.slice(1).sort((a,b)=>a-b); resolve({ medianMs:sorted[Math.floor(sorted.length*.5)], p95Ms:sorted[Math.floor(sorted.length*.95)], scope:"renderer rAF intervals, not GPU frame-time guarantee" }); } }
      requestAnimationFrame(tick);
    }));
    const framesBefore = Number(await page.locator(".character-canvas").getAttribute("data-frames"));
    const measuredAt = Date.now();
    await page.waitForTimeout(2100);
    report.sceneFps = (Number(await page.locator(".character-canvas").getAttribute("data-frames")) - framesBefore) / ((Date.now() - measuredAt) / 1000);
    assert.ok(report.sceneFps > 0 && report.sceneFps < 62);

    await resize(1920,1080);
    await page.locator(".quick-actions-grid").getByRole("button", { name: "Sohbet", exact: true }).click();
    await page.getByRole("heading", { name: "Conversation" }).waitFor();
    const chat = await page.locator(".desktop-chat-panel").boundingBox();
    const stage = await page.locator(".desktop-center-stage").boundingBox();
    assert.ok(chat.width / stage.width < .42);
    await capture("chat-overlay-1920x1080"); await page.keyboard.press("Escape");
    await page.locator(".quick-actions-grid").getByRole("button", { name: "Görsel Oluştur", exact: true }).click();
    await page.getByRole("heading", { name: /Fikri yüzeye çıkar/ }).waitFor();
    await capture("create-stage-1920x1080"); await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Agent Dock", exact: true }).click();
    await page.getByRole("heading", { name: "Agent Dock" }).waitFor();
    await capture("agent-dock-1920x1080"); await page.keyboard.press("Escape");

    // Real network/provider attempt, not mocked data. Zero sources is reported as
    // a limitation, never substituted with the GPU from the concept artwork.
    await page.locator(".desktop-nav-rail").getByRole("button", { name: "Araştır", exact: true }).click();
    await page.getByRole("textbox", { name: "Araştırma sorusu" }).fill("Nvidia");
    await page.getByRole("button", { name: "Araştırmayı başlat" }).click();
    try {
      await page.locator(".research-result-card").waitFor({ timeout: 100000 });
      report.research = { status: "rendered", text: await page.locator(".research-result-card").innerText() };
      await capture("real-research-1920x1080");
      await resize(3440,1440); await capture("real-research-3440x1440");
    } catch {
      report.research = { status: "unavailable", error: await page.locator(".panel-error").allTextContents() };
      await page.keyboard.press("Escape");
    }

    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.getByRole("button", { name: "CALM", exact: true }).click();
    await page.waitForTimeout(200);
    assert.ok(await energy() < .2);
    await page.emulateMedia({ reducedMotion: "no-preference" });
    assert.deepEqual(report.errors, []);
    fs.writeFileSync(path.join(visualDirectory, "validation.json"), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ result:"PASS", runtime:report.runtime.overall, energy:report.energy, sizes:report.sizes, research:report.research, frameTiming:report.frameTiming, screenshots:report.screenshots.length }, null, 2));
  } finally {
    await application.close();
    const resolved = path.resolve(temporary);
    if (resolved.startsWith(path.resolve(os.tmpdir()) + path.sep) && path.basename(resolved).startsWith("akashi-desktop-smoke-")) fs.rmSync(resolved, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
