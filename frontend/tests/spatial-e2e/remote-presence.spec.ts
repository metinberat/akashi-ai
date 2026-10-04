// Remote presence end to end: the built UI as a desktop owner AND as a phone
// (separate browser contexts) against one real AKASHI Core. The phone pairs with a
// code, generates its WebCrypto key, connects over WebSocket, renders the
// authoritative scene and drives it with touch, text and approvals; the desktop
// sees live previews and remote provenance. Simulated devices in one cloud
// browser: NOT a physical iPhone, Mac, Wi-Fi or camera measurement
// (docs/acceptance/remote-spatial-presence-v1-5.md).
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { chromium, expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";

import { CORE, auth, desktopBridge } from "./support";

const ARTIFACTS = path.resolve("tests/spatial-e2e/.artifacts");
const CAMERA_DIR = path.join(ARTIFACTS, "camera");
const IPHONE = {
  viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true,
  userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
};

type CoreEvent = { seq: number; origin: { kind: string; remote?: { device_name: string; modality: string; session: string }; approval?: { device_name: string; by: string } }; command: { type: string } };

async function openDesktop(page: Page) {
  await page.setViewportSize({ width: 1680, height: 960 });
  await desktopBridge(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Spatial Lab", exact: true }).click();
  await expect(page.getByRole("region", { name: "Spatial Lab", exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => localStorage.getItem("akashi-spatial-session"))).not.toBeNull();
  return (await page.evaluate(() => localStorage.getItem("akashi-spatial-session")))!;
}

async function inviteFromDesktop(page: Page): Promise<string> {
  await page.getByRole("button", { name: /^Devices/ }).click();
  const panel = page.getByRole("region", { name: "Remote devices" });
  await panel.getByRole("button", { name: "Create pairing code" }).click();
  const code = await panel.getByTestId("pairing-code").locator("strong").innerText();
  expect(code).toMatch(/^[A-Z0-9]{10}$/u);
  return code;
}

async function pairPhone(context: BrowserContext, code: string, name = "E2E iPhone", prepare?: (page: Page) => void): Promise<Page> {
  const phone = await context.newPage();
  prepare?.(phone);  // listeners must exist before the WebSocket opens
  await phone.goto(`/remote?core=${encodeURIComponent(CORE)}&code=${code}`);
  await phone.getByLabel("Device name").fill(name);
  await phone.getByRole("button", { name: "Pair device" }).click();
  await expect(phone.locator(".remote-connection")).toHaveText("Connected", { timeout: 20_000 });
  return phone;
}

async function events(request: Page["request"], sessionId: string): Promise<CoreEvent[]> {
  return (await (await request.get(`${CORE}/spatial/sessions/${sessionId}/events?after=0&limit=500`, { headers: auth })).json()).events;
}

async function addCalibration(request: Page["request"], sessionId: string): Promise<string> {
  const response = await request.post(`${CORE}/spatial/sessions/${sessionId}/commands`, { headers: auth,
    data: { request: { type: "scene.add_asset", fixture: "calibration" } } });
  expect(response.ok()).toBeTruthy();
  return (await response.json()).targets[0];
}

async function dragOnPhone(phone: Page, objectId: string, dx: number, hold?: () => Promise<void>) {
  const stage = (await phone.locator(".remote-stage").boundingBox())!;
  const [ax, ay] = (await phone.locator(`.remote-label[data-object="${objectId}"]`).getAttribute("data-anchor"))!.split(",").map(Number);
  const x = stage.x + ax * stage.width;
  const y = stage.y + ay * stage.height;
  await phone.mouse.move(x, y);
  await phone.mouse.down();
  for (let i = 1; i <= 12; i += 1) {
    await phone.mouse.move(x + (dx * i) / 12, y, { steps: 2 });
    await phone.waitForTimeout(40);
  }
  if (hold) await hold();
  await phone.waitForTimeout(200);
  await phone.mouse.up();
}

test("a phone pairs, drives the authoritative scene by touch and text, and approves; the desktop sees it live", async ({ page, browser, request }) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(`desktop: ${error.message}`));
  const sessionId = await openDesktop(page);
  const objectId = await addCalibration(request, sessionId);
  await expect(page.locator(`.spatial-object-label[data-object="${objectId}"]`)).toBeVisible();
  const code = await inviteFromDesktop(page);

  const phoneContext = await browser.newContext({ ...IPHONE, baseURL: "http://localhost:3101" });
  const frames: string[] = [];
  const phone = await pairPhone(phoneContext, code, "E2E iPhone", (p) => {
    p.on("pageerror", (error) => errors.push(`phone: ${error.message}`));
    p.on("websocket", (socket) => socket.on("framesent", (frame) => frames.push(String(frame.payload))));
  });

  // The phone renders the same scene (authoritative state from Core).
  const phoneLabel = phone.locator(`.remote-label[data-object="${objectId}"]`);
  await expect(phoneLabel).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("button", { name: /^Devices · 1/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Devices/ })).toHaveAttribute("data-realtime", "online");

  // Touch drag: while the finger is down the desktop shows who holds the object and the live preview.
  const desktopLabel = page.locator(`.spatial-object-label[data-object="${objectId}"]`);
  const before = (await desktopLabel.boundingBox())!;
  await dragOnPhone(phone, objectId, 120, async () => {
    await expect(desktopLabel.locator(".spatial-held")).toHaveText(/E2E iPhone/u, { timeout: 8000 });
    await expect.poll(async () => (await desktopLabel.boundingBox())!.x, { timeout: 8000 }).toBeGreaterThan(before.x + 10);
  });
  await expect(desktopLabel.locator(".spatial-held")).toHaveCount(0, { timeout: 8000 });
  let history = await events(request, sessionId);
  const drag = history.at(-1)!;
  expect(drag.command.type).toBe("object.transform");
  expect(drag.origin.kind).toBe("remote");
  expect(drag.origin.remote).toMatchObject({ device_name: "E2E iPhone", modality: "touch" });
  await phone.screenshot({ path: path.join(ARTIFACTS, "remote-phone.png") });

  // Why did it move? The desktop inspector answers with the device and modality.
  await request.post(`${CORE}/spatial/sessions/${sessionId}/commands`, { headers: auth, data: { request: { type: "selection.select", target: { id: objectId } } } });
  await expect(page.getByTestId("provenance")).toContainText("Remote touch from E2E iPhone", { timeout: 10_000 });
  await page.screenshot({ path: path.join(ARTIFACTS, "remote-desktop.png") });

  // Natural language from the phone runs through the same command path.
  const input = phone.getByLabel("Instruction for AKASHI");
  await input.fill("rotate it 90 degrees");
  await phone.getByRole("button", { name: "Send" }).click();
  await expect(phone.locator(".remote-reply")).toContainText(/Rotated|döndürüldü/u);
  history = await events(request, sessionId);
  expect(history.at(-1)!.origin.remote).toMatchObject({ device_name: "E2E iPhone", modality: "language" });

  // A removal requested on the desktop waits for approval; the phone approves it.
  const pending = await (await request.post(`${CORE}/spatial/sessions/${sessionId}/commands`, { headers: auth,
    data: { request: { type: "scene.remove", target: { id: objectId } }, origin: { kind: "ui", provider: "desktop" } } })).json();
  expect(pending.status).toBe("confirmation_required");
  await expect(phone.locator(".remote-badge")).toHaveText("1", { timeout: 10_000 });
  await phone.getByRole("button", { name: /Approvals/ }).click();
  const approvals = phone.getByRole("region", { name: "Pending approvals" });
  await expect(approvals).toContainText("Remove");
  await expect(approvals).toContainText("Requested by UI control");
  await approvals.getByRole("button", { name: "Approve" }).click();
  await expect(phoneLabel).toHaveCount(0, { timeout: 10_000 });
  await expect(desktopLabel).toHaveCount(0, { timeout: 10_000 });
  history = await events(request, sessionId);
  expect(history.at(-1)!.command.type).toBe("object.remove");
  expect(history.at(-1)!.origin.approval).toMatchObject({ device_name: "E2E iPhone", by: "device" });
  const audit = await (await request.get(`${CORE}/remote/audit`, { headers: auth })).json();
  expect(audit.events.map((e: { kind: string }) => e.kind)).toEqual(expect.arrayContaining(["device.paired", "session.opened", "approval.decided"]));
  expect((await (await request.post(`${CORE}/remote/audit/verify`, { headers: auth })).json()).verified).toBe(true);
  expect((await (await request.post(`${CORE}/spatial/sessions/${sessionId}/replay/verify`, { headers: auth })).json()).verified).toBe(true);

  // Traffic: small JSON envelopes only.
  expect(frames.length).toBeGreaterThan(5);
  for (const frame of frames) {
    expect(frame.length).toBeLessThan(65_536);
    const parsed = JSON.parse(frame);
    expect(parsed.type === "auth" || parsed.v === 1).toBe(true);
  }
  expect(errors).toEqual([]);
  await phoneContext.close();
});

test("network loss on the phone recovers to Core's state; revocation from the desktop stops it at once", async ({ page, browser, request }) => {
  test.setTimeout(120_000);
  const sessionId = await openDesktop(page);
  const objectId = await addCalibration(request, sessionId);
  const code = await inviteFromDesktop(page);
  const phoneContext = await browser.newContext({ ...IPHONE, baseURL: "http://localhost:3101" });
  const phone = await pairPhone(phoneContext, code, "Flaky iPhone");
  await expect(phone.locator(`.remote-label[data-object="${objectId}"]`)).toBeVisible({ timeout: 15_000 });

  await phoneContext.setOffline(true);
  await expect(phone.locator(".remote-connection")).toHaveText(/Reconnecting|Connecting/u, { timeout: 30_000 });
  // While the phone is away the scene changes on the desktop.
  for (const dx of [0.4, 0.3]) {
    await request.post(`${CORE}/spatial/sessions/${sessionId}/commands`, { headers: auth,
      data: { request: { type: "object.transform", target: { id: objectId }, mode: "translate", delta: [dx, 0, 0] } } });
  }
  const core = await (await request.get(`${CORE}/spatial/sessions/${sessionId}`, { headers: auth })).json();
  await phoneContext.setOffline(false);
  await expect(phone.locator(".remote-connection")).toHaveText("Connected", { timeout: 30_000 });
  await phone.getByRole("button", { name: "Debug" }).click();
  const debug = phone.getByRole("region", { name: "Remote debug" });
  await expect(debug).toContainText(`rev ${core.session.revision}`, { timeout: 15_000 });
  await expect(debug).toContainText(core.session.digest.slice(0, 18));

  page.on("dialog", (dialog) => void dialog.accept());
  const panel = page.getByRole("region", { name: "Remote devices" });
  await panel.locator("li", { hasText: "Flaky iPhone" }).getByRole("button", { name: "Revoke" }).click();
  await expect(phone.getByRole("heading", { name: "This device was revoked" })).toBeVisible({ timeout: 10_000 });
  const devices = await (await request.get(`${CORE}/remote/devices`, { headers: auth })).json();
  const revoked = devices.devices.find((d: { name: string }) => d.name === "Flaky iPhone");
  expect(revoked.revoked).toBe(true);
  expect(revoked.sessions).toEqual([]);
  await phoneContext.close();
});

test("hand tracking runs on the phone; only landmark-derived anchors and commands leave it (no video)", async ({ page, request }) => {
  test.setTimeout(180_000);
  const sessionId = await openDesktop(page);
  await addCalibration(request, sessionId);
  const code = await inviteFromDesktop(page);
  let cameraBrowser: Browser | null = null;
  try {
    cameraBrowser = await chromium.launch({
      executablePath: process.env.CHROMIUM_PATH || undefined,
      args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", `--use-file-for-fake-video-capture=${path.join(CAMERA_DIR, "fist.y4m")}`],
    });
    const context = await cameraBrowser.newContext({ ...IPHONE, baseURL: "http://localhost:3101" });
    const sent: Array<{ kind: string; bytes: number; body: Record<string, unknown> }> = [];
    const uploads: number[] = [];
    const phone = await pairPhone(context, code, "Camera iPhone", (p) => {
      p.on("websocket", (socket) => socket.on("framesent", (frame) => {
        const text = String(frame.payload);
        const parsed = JSON.parse(text);
        sent.push({ kind: parsed.kind ?? parsed.type, bytes: text.length, body: parsed.body ?? {} });
      }));
      p.on("request", (req) => { const body = req.postDataBuffer(); if (body) uploads.push(body.length); });
    });
    await phone.getByRole("button", { name: "Hands" }).click();
    const withAnchors = () => sent.filter((m) => m.kind === "spatial.presence" && Object.keys((m.body.anchors as object) ?? {}).length > 0);
    await expect.poll(() => withAnchors().length, { timeout: 120_000 }).toBeGreaterThan(0);
    await phone.waitForTimeout(3000);
    const devices = await (await request.get(`${CORE}/remote/devices`, { headers: auth })).json();
    const live = devices.devices.find((d: { name: string }) => d.name === "Camera iPhone").sessions[0];
    expect(live.capabilities.find((c: { name: string }) => c.name === "camera").state).toBe("active");
    expect(live.capabilities.find((c: { name: string }) => c.name === "hand_tracking").state).toBe("active");
    const presence = sent.filter((m) => m.kind === "spatial.presence");
    const anchor = Object.values(withAnchors()[0].body.anchors as Record<string, { position: number[] }>)[0];
    expect(anchor.position).toHaveLength(3);
    const kinds = new Set(sent.map((m) => m.kind));
    for (const kind of kinds) expect(["auth", "ping", "spatial.subscribe", "spatial.presence", "capabilities.update", "approvals.list"]).toContain(kind);
    const largest = Math.max(...sent.map((m) => m.bytes), ...uploads, 0);
    const total = sent.reduce((sum, m) => sum + m.bytes, 0) + uploads.reduce((a, b) => a + b, 0);
    mkdirSync(path.join(ARTIFACTS, "remote"), { recursive: true });
    writeFileSync(path.join(ARTIFACTS, "remote", "camera-traffic.json"), JSON.stringify({
      scope: "Cloud: Chromium fake camera with a still photo; hand tracking on the simulated phone. Not a physical device.",
      messages: sent.length, kinds: [...kinds], largest_message_bytes: largest, total_uplink_bytes: total, presence_messages: presence.length,
    }, null, 2));
    expect(largest).toBeLessThan(4096);  // a single 640×480 frame would be ~100 KB as JPEG, ~1.2 MB raw
    expect(sent.some((m) => /data:image|\/9j\//u.test(JSON.stringify(m.body)))).toBe(false);
    await context.close();
  } finally {
    await cameraBrowser?.close();
  }
});
