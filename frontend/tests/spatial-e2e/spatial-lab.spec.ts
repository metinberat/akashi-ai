// Real end-to-end: built UI ↔ real AKASHI Core ↔ FORM library built by FORM's
// own code (SYNTHETIC GLBs). Hand input here is the mouse-driven SIMULATED hand
// running through the real tracker/pose/interaction pipeline — not a webcam.
import { expect, test, type Page } from "@playwright/test";

const CORE = "http://127.0.0.1:8017";
const TOKEN = "spatial-e2e-token-0000000000000000000000";
const auth = { Authorization: `Bearer ${TOKEN}` };
type CoreEvent = { origin: { kind: string; provider: string; input: Record<string, unknown> }; command: { type: string; transform?: { position: number[]; scale: number } }; request: Record<string, unknown> };

async function desktopBridge(page: Page) {
  await page.addInitScript(({ core, token }) => {
    const toBase64 = (bytes: Uint8Array) => { let s = ""; for (const b of bytes) s += String.fromCharCode(b); return btoa(s); };
    const fromBase64 = (value: string) => Uint8Array.from(atob(value), (c) => c.charCodeAt(0));
    const runtime = { overall: "READY", coreMode: "local", components: Object.fromEntries(["core", "agent", "voice", "ollama", "comfyui"].map((name) => [name, { state: "READY" }])) };
    // Same contract as desktop/app/main.cjs akashi:api:fetch, forwarding to the real Core.
    window.akashiDesktop = {
      platform: "win32",
      config: { load: async () => ({ baseUrl: core, tokenStored: true, coreMode: "local" }) },
      provider: { load: async () => ({ aiProvider: "mock", geminiKeyStored: false, geminiModel: "" }) },
      runtime: { status: async () => runtime, whenReady: async () => runtime, onState: () => () => {} },
      windowControls: { isMaximized: async () => false, onState: () => () => {} },
      agent: { execute: async () => ({ ok: false }), status: async () => ({}) },
      voice: { status: async () => ({ available: false }), stop: async () => true, onState: () => () => {} },
      api: { fetch: async (request: { path: string; method: string; headers: Record<string, string>; body: { kind: string; value?: string; entries?: Array<{ kind: string; name: string; value: string; filename?: string; type?: string }> } }) => {
        let body: BodyInit | undefined;
        const headers = new Headers(request.headers);
        if (request.body?.kind === "text") body = request.body.value;
        if (request.body?.kind === "base64") body = fromBase64(request.body.value!);
        if (request.body?.kind === "form") {
          const form = new FormData();
          for (const entry of request.body.entries ?? []) {
            if (entry.kind === "text") form.append(entry.name, entry.value);
            else form.append(entry.name, new Blob([fromBase64(entry.value)], { type: entry.type }), entry.filename);
          }
          body = form;
          headers.delete("content-type");
        }
        headers.set("Authorization", `Bearer ${token}`);
        const response = await fetch(core + request.path, { method: request.method, headers, body });
        return { status: response.status, statusText: response.statusText, headers: Object.fromEntries(response.headers.entries()), body: toBase64(new Uint8Array(await response.arrayBuffer())) };
      } },
    } as unknown as Window["akashiDesktop"];
  }, { core: CORE, token: TOKEN });
}

async function sessionId(page: Page) {
  return page.evaluate(() => localStorage.getItem("akashi-spatial-session"));
}

async function say(page: Page, text: string) {
  const input = page.getByLabel("Spatial command");
  await input.fill(text);
  await input.press("Enter");
}

test("desktop Spatial Lab: FORM load, language, simulated-hand drag, undo, replay, confirmed removal", async ({ page, request }) => {
  await page.setViewportSize({ width: 1680, height: 960 });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await desktopBridge(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Spatial Lab", exact: true }).click();
  const lab = page.getByRole("region", { name: "Spatial Lab", exact: true });
  await expect(lab).toBeVisible();
  await expect(lab).toContainText("Camera-backed 2.5D");
  const library = page.getByRole("region", { name: "Spatial library" });
  await expect(library).toContainText("Hero Prototype");
  await expect(library).toContainText("2/3 verified versions");

  await library.getByRole("button", { name: "Load latest" }).click();
  const label = page.locator(".spatial-object-label", { hasText: "Hero Prototype V03" });
  await expect(label).toBeVisible();
  await expect(page.getByTestId("spatial-viewport")).toHaveAttribute("data-models", "1", { timeout: 20_000 });
  const inspector = page.getByRole("region", { name: "Object inspector" });
  await expect(inspector).toContainText("SHA-256 matches FORM export record");
  await expect(inspector).toContainText("Walk Cycle");
  await expect(inspector).toContainText("4 joints");

  await say(page, "play the walking animation");
  await expect(page.locator(".spatial-reply")).toContainText("Playing Walk Cycle");
  await say(page, "make it bigger");
  await expect(page.locator(".spatial-reply")).toContainText("1.25×");
  await say(page, "play the dance animation");
  await expect(page.locator(".spatial-reply")).toContainText("Available: Idle, Walk Cycle");
  await say(page, "iskeleti göster");
  await expect(inspector.getByRole("button", { name: "Rig" })).toHaveAttribute("aria-pressed", "true");
  await say(page, "load the best FORM version");
  await expect(page.locator(".spatial-object-label", { hasText: "Hero Prototype V01" })).toBeVisible();
  await expect(inspector).toContainText("best at import");
  await page.getByRole("button", { name: "Debug" }).click();
  await page.waitForTimeout(1200);
  await page.screenshot({ path: "tests/spatial-e2e/.artifacts/desktop-spatial-lab.png" });
  await page.getByRole("button", { name: "Debug" }).click();

  // Simulated hand: pinch on the character's chest and drag it right.
  await page.getByRole("button", { name: "Simulate" }).click();
  await expect(page.locator(".spatial-input-state")).toContainText("SIMULATED HANDS");
  const anchor = (await page.locator(".spatial-object-label").first().getAttribute("data-anchor"))!.split(",").map(Number);
  const stage = (await page.locator(".spatial-stage").boundingBox())!;
  const start = { x: stage.x + anchor[0] * stage.width, y: stage.y + anchor[1] * stage.height };
  const before = await (await request.get(`${CORE}/spatial/sessions/${await sessionId(page)}`, { headers: auth })).json();
  const objectId = before.state.order[0];
  await page.mouse.move(start.x, start.y);
  await page.waitForTimeout(400);
  await page.mouse.down();
  await page.waitForTimeout(250);
  for (let i = 1; i <= 15; i += 1) {
    await page.mouse.move(start.x + i * 10, start.y);
    await page.waitForTimeout(40);
  }
  await page.waitForTimeout(350);
  await page.screenshot({ path: "tests/spatial-e2e/.artifacts/desktop-spatial-drag.png" });
  await page.mouse.up();
  await expect.poll(async () => {
    const events = await (await request.get(`${CORE}/spatial/sessions/${await sessionId(page)}/events`, { headers: auth })).json();
    return (events.events as CoreEvent[]).filter((e) => e.origin.kind === "gesture" && e.command.type === "object.transform").length;
  }, { timeout: 10_000 }).toBe(1);
  const events = (await (await request.get(`${CORE}/spatial/sessions/${await sessionId(page)}/events`, { headers: auth })).json()).events as CoreEvent[];
  const gesture = events.find((e) => e.origin.kind === "gesture" && e.command.type === "object.transform")!;
  expect(gesture.origin.provider).toBe("pointer-simulated");
  expect(gesture.origin.input.gesture).toBe("one_hand_move");
  expect(gesture.origin.input.ended_by).toBe("release");
  expect(gesture.command.transform!.position[0]).toBeGreaterThan(before.state.objects[objectId].transform.position[0] + 0.2);
  expect(String(gesture.request.lease_id)).toMatch(/^lease-/);
  expect(gesture.command.transform!.scale).toBe(1.25); // the language-made scale survives the gesture move
  const origins = new Set(events.map((e) => e.origin.kind));
  expect([...origins].sort()).toEqual(["gesture", "language", "ui"]);

  // Undo the drag (one history, every origin).
  await page.getByRole("button", { name: "Simulate" }).click();
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect.poll(async () => (await (await request.get(`${CORE}/spatial/sessions/${await sessionId(page)}`, { headers: auth })).json()).state.objects[objectId].transform.position[0]).toBe(before.state.objects[objectId].transform.position[0]);

  // Replay: step through and verify determinism server-side.
  await page.getByRole("button", { name: "Replay", exact: true }).click();
  const replay = page.getByRole("region", { name: "Replay timeline" });
  await expect(replay).toContainText("Step");
  await replay.getByRole("button", { name: "◀ Step" }).click();
  await expect(replay).toContainText("GESTURE");
  await replay.getByRole("button", { name: "Verify determinism" }).click();
  await expect(replay).toContainText("identical state");
  await page.screenshot({ path: "tests/spatial-e2e/.artifacts/desktop-spatial-replay.png" });
  await page.getByRole("button", { name: "Exit replay" }).click();

  // Destructive language request asks first, then is undoable.
  await say(page, "remove it");
  await expect(page.locator(".spatial-reply")).toContainText("Confirmation needed");
  await expect(page.locator(".spatial-object-label")).toHaveCount(1);
  await page.locator(".spatial-reply").getByRole("button", { name: "Confirm" }).click();
  await expect(page.locator(".spatial-object-label")).toHaveCount(0);
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.locator(".spatial-object-label")).toHaveCount(1);

  const verified = await (await request.post(`${CORE}/spatial/sessions/${await sessionId(page)}/replay/verify`, { headers: auth })).json();
  expect(verified.verified && verified.matches_live_state).toBe(true);
  expect(errors).toEqual([]);
});

test("web shell: Spatial Lab from More, calibration fixture, HUD toggle, camera failure degrades gracefully", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript((token) => {
    localStorage.setItem("akashi_backend_url", "https://core.spatial.test");
    sessionStorage.setItem("akashi_backend_token", token);
  }, TOKEN);
  await page.route("https://core.spatial.test/**", async (route) => {
    const response = await route.fetch({ url: route.request().url().replace("https://core.spatial.test", CORE) });
    await route.fulfill({ response });
  });
  await page.goto("/");
  await page.getByRole("navigation", { name: "Ana menü" }).getByRole("button", { name: /More/ }).click();
  await page.getByRole("button", { name: /Spatial Lab/ }).click();
  const lab = page.getByRole("region", { name: "Spatial Lab", exact: true });
  await expect(lab).toBeVisible();
  await page.getByRole("button", { name: /Add 1.70 m calibration block/ }).click();
  await expect(page.locator(".spatial-object-label", { hasText: "Calibration block" })).toBeVisible();
  await expect(page.getByTestId("spatial-viewport")).toHaveAttribute("data-models", "1", { timeout: 20_000 });
  await page.getByRole("button", { name: "Hide HUD" }).click();
  await expect(page.locator(".spatial-object-label")).toHaveCount(0);
  await page.getByRole("button", { name: "Show HUD" }).click();
  await expect(page.locator(".spatial-object-label")).toHaveCount(1);
  // No camera device in this browser: the provider reports it and the scene stays usable.
  await page.getByRole("button", { name: "Camera", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: /camera/i }).first()).toBeVisible();
  await say(page, "rotate it 90 degrees");
  await expect(page.locator(".spatial-reply")).toContainText("90°");
  expect(errors).toEqual([]);
});
