import { test, expect } from "@playwright/test";

test("desktop decisions use research data; only explicit source click opens the browser", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.addInitScript(() => {
    const state = window as typeof window & { __opened: string[]; __requests: string[] };
    state.__opened = []; state.__requests = [];
    // The desktop bridge transports response bodies as base64 of UTF-8 BYTES.
    // btoa() alone encodes UTF-16 code units and throws on any non-Latin-1
    // character, which this fixture's Turkish payloads contain.
    const encodeBody = (value: unknown) => {
      const bytes = new TextEncoder().encode(JSON.stringify(value));
      let binary = "";
      for (const byte of bytes) binary += String.fromCharCode(byte);
      return btoa(binary);
    };
    const runtime = { overall: "READY", coreMode: "local", components: Object.fromEntries(["core", "agent", "voice", "ollama", "comfyui"].map(name => [name, { state: "READY" }])) };
    window.akashiDesktop = {
      platform: "win32", config: { load: async () => ({ baseUrl: "https://api.example.test", tokenStored: true }) },
      provider: { load: async () => ({ aiProvider: "mock", geminiKeyStored: false, geminiModel: "" }) },
      windowControls: { isMaximized: async () => false, onState: () => () => {} },
      runtime: { status: async () => runtime, whenReady: async () => runtime, onState: () => () => {} },
      agent: { execute: async () => ({ ok: false }), status: async () => ({}) },
      voice: { status: async () => ({ available: false }), stop: async () => true, onState: () => () => {} },
      shell: { openExternal: async (url: string) => { state.__opened.push(url); return true; } },
      api: { fetch: async (request: { path: string }) => {
        state.__requests.push(request.path);
        let value: unknown = {};
        if (request.path === "/health" || request.path === "/auth/check") value = { status: "ok" };
        if (request.path === "/system/health") value = { core: { status: "online" }, auth: { status: "authorized" }, model: { status: "online" }, ollama: { status: "online" }, images: { status: "offline" }, research: { status: "configured" }, desktop_agent: { status: "online" } };
        if (request.path === "/tasks") value = { tasks: [] };
        if (request.path.startsWith("/memory/conversations")) value = { conversations: [], messages: [] };
        if (request.path.startsWith("/memory?")) value = { memories: [] };
        if (request.path.startsWith("/intelligence/")) value = [];
        if (request.path === "/research") value = { question: "GPU video araştır", mode: "normal", provider: "test-fixture", status: "completed", synthesis_status: "source-only", summary: "Fixture source metadata, not a playable clip.", findings: [], sources: [{ title: "Source preview", url: "https://example.test/video", snippet: "Preview text", provider: "test-fixture", relevance: 1 }] };
        if (request.path.startsWith("/events/recent")) value = { cursor: 1, instance: "fixture", events: request.path.endsWith("after=0") ? [{ id: 1, timestamp: new Date().toISOString(), type: "research.progress", data: { state: "completed", source_count: 1 } }] : [] };
        return { status: 200, headers: { "content-type": "application/json" }, body: encodeBody(value) };
      } },
    } as unknown as Window["akashiDesktop"];
  });
  await page.goto("/");
  await expect(page.locator(".desktop-command-center")).toBeVisible();
  await page.locator(".desktop-command-form textarea").fill("GPU video araştır");
  await page.locator(".desktop-command-form textarea").press("Enter");
  const card = page.getByRole("region", { name: "Araştırma sonucu" });
  await expect(card).toContainText("Source preview");
  await expect(card).toContainText("VİDEO KESİTİ YOK");
  expect(await page.evaluate(() => (window as unknown as { __opened: string[] }).__opened)).toEqual([]);
  await card.getByRole("button", { name: "Detaylar" }).click();
  await expect(card).toContainText("FINDINGS / SOURCE CONTEXT");
  await card.getByRole("button", { name: "Kaynağı aç" }).click();
  expect(await page.evaluate(() => (window as unknown as { __opened: string[] }).__opened)).toEqual(["https://example.test/video"]);
  await card.getByRole("button", { name: "Bu mu?" }).click();
  await expect.poll(() => page.evaluate(() => (window as unknown as { __requests: string[] }).__requests.filter(path => path === "/research").length)).toBe(2);
  expect(await page.evaluate(() => (window as unknown as { __requests: string[] }).__requests.includes("/chat"))).toBe(false);
  await expect(page.locator(".activity-instrument")).toContainText("Tamamlandı");
});
