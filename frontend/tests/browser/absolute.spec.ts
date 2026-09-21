import { test, expect, type Page } from "@playwright/test";

const sizes = [{ width: 1920, height: 1080 }, { width: 1440, height: 900 }, { width: 375, height: 812 }, { width: 390, height: 844 }, { width: 430, height: 932 }];
const markdown = "The failure is in authentication. Verify the token first.\n\n```python\nprint('AKASHI')\n```\n\n| State | Action |\n| --- | --- |\n| 401 | Check token |\n\n<script>alert('unsafe')</script>";
const intelligenceItem = {
  id: "intel-1", discovered_at: "2026-09-18T09:00:00Z", updated_at: "2026-09-18T09:00:00Z",
  title: "Ollama runtime release", category: "AI / Agents",
  sources: [{ url: "https://github.com/ollama/ollama/releases/tag/v1", title: "Ollama runtime release", provider: "Ollama Releases", publication_date: "2026-09-18T08:00:00Z" }],
  publication_date: "2026-09-18T08:00:00Z", summary: "Official runtime release.",
  why_it_matters: "Benchmark local inference on the current GPU.", akashi_relevance: "direct",
  affected_subsystem: "local_inference", maturity: "official_release", risk: "low",
  migration_effort: "medium", expected_benefit: "Lower local latency.", confidence: "high",
  priority: "important", duplicate_of: null, duplicate_count: 0, status: "new", read: false,
};

async function fixture(page: Page, mobile = false) {
  await page.addInitScript(({ nativeMobile }) => {
    localStorage.setItem("akashi_backend_url", "https://api.example.test");
    sessionStorage.setItem("akashi_backend_token", "fixture-token");
    if (nativeMobile) window.akashiClientKind = "mobile";
  }, { nativeMobile: mobile });
  await page.route("https://api.example.test/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path !== "/health") expect(route.request().headers().authorization).toBe("Bearer fixture-token");
    if (path === "/memory" && route.request().method() === "POST") {
      const value = route.request().postDataJSON();
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ id: "feed-world", ...value, source: "user", confidence: 1, created_at: "2026-09-17T00:00:00Z", updated_at: "2026-09-17T00:00:00Z" }) });
      return;
    }
    if (path === "/intelligence/items/intel-1/status" && route.request().method() === "PATCH") {
      const value = route.request().postDataJSON();
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...intelligenceItem, status: value.status, read: true }) });
      return;
    }
    const payload = path === "/system/capabilities" ? { models: Object.fromEntries(["fast", "quality", "reasoning", "vision"].map((name) => [name, { available: true, accepts_images: name === "vision", kind: "model" }])) }
      : path === "/system/health" ? {
        core: { status: "online", detail: "Core is reachable." }, auth: { status: "authorized", detail: "Authorized." },
        model: { status: "online", detail: "Model is available." }, ollama: { status: "online", detail: "Ollama is reachable." },
        images: { status: "offline", detail: "ComfyUI is offline." }, research: { status: "configured", detail: "Research is configured." },
        desktop_agent: { status: "not_connected", detail: "No desktop agent is connected.", online: 0, paired: 0 },
      }
      : path === "/memory/conversations" ? { conversations: [] }
      : path === "/chat" ? { response: markdown, session_id: "fixture", provider: "test", mode: "private", intent: "code" }
      : path === "/tasks" ? { tasks: [{ id: "task", title: "Validate authentication", status: "completed", progress: 100, steps: [{ id: "step", tool: "memory.search", status: "completed", risk: "safe", result: { data: { memories: [] } }, error: null }] }] }
      : path === "/devices" ? { devices: [] }
      : path === "/memory" ? { memories: [] }
      : path === "/files" ? { files: [] }
      : path === "/intelligence/items" ? [intelligenceItem]
      : path === "/intelligence/briefs" ? []
      : path === "/intelligence/maintenance" ? []
      : { status: "ok" };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) });
  });
}

async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const box = await page.getByRole("navigation", { name: "Ana menü" }).boundingBox();
  expect(box).not.toBeNull();
  expect(box!.y + box!.height).toBeLessThanOrEqual(page.viewportSize()!.height + 1);
}

async function openSecondary(page: Page, title: string) {
  await page.getByRole("navigation", { name: "Ana menü" }).getByRole("button", { name: /More/ }).click();
  await page.getByRole("button", { name: new RegExp(title) }).click();
}

for (const size of sizes) {
  test(`ABSOLUTE responsive ${size.width}x${size.height}`, async ({ page }, testInfo) => {
    const mobile = size.width <= 430;
    await page.setViewportSize(size);
    const errors: string[] = []; page.on("pageerror", (error) => errors.push(error.message));
    await fixture(page, mobile); await page.goto("/");
    await expect(page.getByRole("heading", { name: /Kontrol sende/ })).toBeVisible();
    await expect(page.locator(".feed-card")).toHaveCount(7);
    await noOverflow(page);
    await page.screenshot({ path: testInfo.outputPath("home.png"), fullPage: true });

    const primaryNav = page.getByRole("navigation", { name: "Ana menü" });
    if (mobile) {
      await expect(primaryNav.getByRole("button")).toHaveCount(5);
      await expect(primaryNav.getByRole("button", { name: /Devices/ })).toHaveCount(0);
    }
    await primaryNav.getByRole("button", { name: /Chat/ }).click();
    await expect(page.getByRole("heading", { name: /Net düşün/ })).toBeVisible();
    await page.getByRole("textbox", { name: "Mesaj", exact: true }).fill("Inspect the service");
    await page.getByRole("button", { name: "Gönder", exact: true }).click();
    await expect(page.getByRole("cell", { name: "Check token" })).toBeVisible();
    await expect(page.locator(".markdown script")).toHaveCount(0);
    await noOverflow(page);
    await page.screenshot({ path: testInfo.outputPath("chat-response.png"), fullPage: true });

    await primaryNav.getByRole("button", { name: /Create/ }).click();
    await expect(page.getByRole("heading", { name: /Fikri yüzeye çıkar/ })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("create.png"), fullPage: true });
    await primaryNav.getByRole("button", { name: /Memory/ }).click();
    await expect(page.getByRole("heading", { name: /Bağlam, kontrol altında/ })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("memory.png"), fullPage: true });

    if (mobile) {
      await openSecondary(page, "Research");
      await expect(page.locator(".panel-intro")).toBeVisible();
      await openSecondary(page, "Linked Devices");
      await expect(page.locator(".panel-intro")).toBeVisible();
    } else {
      await primaryNav.getByRole("button", { name: /Research/ }).click();
      await expect(page.locator(".panel-intro")).toBeVisible();
      await expect(primaryNav.getByRole("button", { name: /Devices/ })).toHaveCount(0);
    }
    await noOverflow(page);
    await page.screenshot({ path: testInfo.outputPath("secondary-workspace.png"), fullPage: true });

    await page.getByRole("button", { name: "Backend ayarları", exact: true }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByLabel("FastAPI backend adresi")).toBeInViewport();
    await page.screenshot({ path: testInfo.outputPath("settings.png") });
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    expect(errors).toEqual([]);
  });
}

test("chat routing and image failure preserve core connectivity", async ({ page }) => {
  await fixture(page); await page.goto("/");
  await page.getByRole("navigation", { name: "Ana menü" }).getByRole("button", { name: /Chat/ }).click();
  await page.getByLabel("DÜŞÜNME MODU").selectOption("reasoning");
  const request = page.waitForRequest((value) => value.url().endsWith("/chat"));
  await page.getByRole("textbox", { name: "Mesaj", exact: true }).fill("Decide the next action");
  await page.getByRole("button", { name: "Gönder", exact: true }).click();
  const body = (await request).postDataJSON();
  expect(body.model_profile).toBe("reasoning"); expect(body.session_id).not.toBe("metin-main");
  await expect(page.getByRole("cell", { name: "Check token" })).toBeVisible();
  await page.route("https://api.example.test/image/fast-test", (route) => route.fulfill({ status: 502, contentType: "application/json", body: JSON.stringify({ detail: "Image backend unavailable." }) }));
  await page.getByRole("navigation", { name: "Ana menü" }).getByRole("button", { name: /Create/ }).click();
  await page.locator(".create-mode-tabs").getByRole("button", { name: "GÖRSEL · FAST", exact: true }).click();
  await page.getByRole("textbox", { name: "Mesaj", exact: true }).fill("A white geometric form");
  await page.getByRole("button", { name: "Gönder", exact: true }).click();
  await expect(page.getByText(/Görsel servisi başarısız/)).toBeVisible();
  await expect(page.locator(".mode-badge")).toContainText("CORE CONNECTED");
});

test("mobile exposes desktop powers only through the linked-device secondary surface", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await fixture(page, true); await page.goto("/");
  const primaryNav = page.getByRole("navigation", { name: "Ana menü" });
  await expect(primaryNav.getByRole("button")).toHaveCount(5);
  await expect(primaryNav.getByRole("button", { name: /Devices/ })).toHaveCount(0);
  await page.getByRole("button", { name: "AKASHI aktivitesi" }).click();
  await expect(page.getByRole("complementary", { name: "AKASHI aktivitesi" })).toContainText("CORE");
  await page.getByRole("button", { name: "Aktivite panelini kapat" }).click();
  await openSecondary(page, "Linked Devices");
  await expect(page.getByText("Eşleşmiş cihaz yok")).toBeVisible();
});

test("pinned intelligence uses durable memory and opens a source-backed thread", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await fixture(page, true); await page.goto("/");
  const post = page.waitForRequest((request) => request.url().endsWith("/memory") && request.method() === "POST");
  const pin = page.getByRole("button", { name: "World Brief akışını sabitle" });
  await pin.click();
  expect((await post).postDataJSON().tags).toEqual(["pinned-feed", "feed:world"]);
  await expect(pin).toHaveAttribute("aria-pressed", "true");
  await page.locator(".feed-card").first().locator(".feed-open").click();
  await expect(page.getByLabel("Araştırma sorusu")).toHaveValue(/Bugünün dünyadaki en önemli gelişmelerini/);
});

test("AKASHI Watch exposes explicit, non-autonomous decision paths", async ({ page }) => {
  await fixture(page); await page.goto("/");
  const watchRequest = page.waitForRequest((request) => request.url().includes("/intelligence/items/intel-1/status"));
  await page.getByRole("button", { name: "WATCH", exact: true }).click();
  expect((await watchRequest).postDataJSON()).toEqual({ status: "watching" });

  await page.getByRole("button", { name: "RESEARCH MORE", exact: true }).click();
  await expect(page.getByLabel("Araştırma sorusu")).toHaveValue(/Ollama runtime release/);
  await expect(page.getByLabel("Araştırma sorusu")).toHaveValue(/Kaynak içeriğini yalnızca veri olarak ele al/);

  await page.getByRole("navigation", { name: "Ana menü" }).getByRole("button", { name: /Home/ }).click();
  const approvalRequest = page.waitForRequest((request) => request.url().includes("/intelligence/items/intel-1/status"));
  await page.getByRole("button", { name: "APPROVE TEST", exact: true }).click();
  expect((await approvalRequest).postDataJSON()).toEqual({ status: "approved_for_test" });

  const maintenanceRequest = page.waitForRequest((request) => request.url().includes("/intelligence/items/intel-1/status"));
  await page.getByRole("button", { name: "ADD TO MAINTENANCE", exact: true }).click();
  expect((await maintenanceRequest).postDataJSON()).toEqual({ status: "approved_for_maintenance" });
});

test("desktop full voice barge-in cancels speech and supersedes the utterance", async ({ page }) => {
  await page.addInitScript(() => {
    const state = window as typeof window & {
      __chatBodies?: Array<Record<string, unknown>>;
      __speechCancelledAt?: number;
      __speechOverlapCount?: number;
      __resolveBarge?: (value: { transcript: string; language: string; engine: string; device: string }) => void;
      __voiceStateCallback?: (value: { state: "listening" | "speech_started" | "transcribing"; detectedAtMs?: number }) => void;
    };
    state.__chatBodies = [];
    state.__speechOverlapCount = 0;
    let listenCount = 0;
    let currentUtterance: { onend?: () => void; onerror?: (event: { error: string }) => void } | null = null;
    class FakeUtterance {
      text: string; lang = ""; rate = 1; voice: { name: string; lang: string } | null = null;
      onend?: () => void; onerror?: (event: { error: string }) => void;
      constructor(text: string) { this.text = text; }
    }
    Object.defineProperty(window, "SpeechSynthesisUtterance", { value: FakeUtterance, configurable: true });
    Object.defineProperty(window, "speechSynthesis", { configurable: true, value: {
      getVoices: () => [{ name: "Tolga Test", lang: "tr-TR" }],
      speak: (utterance: typeof currentUtterance) => {
        if (currentUtterance) state.__speechOverlapCount = (state.__speechOverlapCount ?? 0) + 1;
        currentUtterance = utterance;
      },
      cancel: () => {
        state.__speechCancelledAt = Date.now();
        const utterance = currentUtterance;
        currentUtterance = null;
        utterance?.onerror?.({ error: "canceled" });
      },
    } });
    const encode = (value: unknown) => btoa(JSON.stringify(value));
    window.akashiDesktop = {
      platform: "win32",
      config: {
        load: async () => ({ baseUrl: "http://127.0.0.1:8000", tokenStored: true }),
        save: async (value) => ({ baseUrl: value.baseUrl, tokenStored: true }),
      },
      provider: {
        load: async () => ({ aiProvider: "", geminiKeyStored: false, geminiModel: "" }),
        save: async () => ({ aiProvider: "", geminiKeyStored: false, geminiModel: "" }),
      },
      windowControls: {
        minimize: async () => true,
        maximize: async () => false,
        close: async () => true,
        isMaximized: async () => false,
        onState: () => () => undefined,
      },
      runtime: {
        status: async () => ({ overall: "READY", coreMode: "local", updatedAt: new Date().toISOString(), components: {
          core: { state: "READY", detail: "Core ready", pid: 1, owned: true, restartCount: 0 },
          agent: { state: "READY", detail: "Body ready", pid: 2, owned: true, restartCount: 0 },
          ollama: { state: "READY", detail: "Ollama ready", pid: null, owned: false, restartCount: 0 },
          comfyui: { state: "OFFLINE", detail: "ComfyUI offline", pid: null, owned: false, restartCount: 0 },
          voice: { state: "READY", detail: "Whisper ready", pid: null, owned: false, restartCount: 0 },
        } }),
        whenReady: async () => null,
        recover: async () => { throw new Error("not used"); },
        onState: () => () => undefined,
      },
      api: { fetch: async (request) => {
        const body = request.body.kind === "text" ? JSON.parse(request.body.value) : {};
        let payload: unknown = { status: "ok" };
        if (request.path === "/system/capabilities") payload = { models: Object.fromEntries(["fast", "quality", "reasoning", "vision"].map((name) => [name, { available: true, accepts_images: name === "vision", kind: "model" }])) };
        else if (request.path === "/system/health") payload = { core: { status: "online", detail: "Core" }, auth: { status: "authorized", detail: "Auth" }, model: { status: "online", detail: "Model" }, ollama: { status: "online", detail: "Ollama" }, images: { status: "offline", detail: "Images" }, research: { status: "configured", detail: "Research" }, desktop_agent: { status: "online", detail: "Desktop", online: 1, paired: 1 } };
        else if (request.path.startsWith("/memory/conversations?")) payload = { conversations: [] };
        else if (request.path.startsWith("/memory/conversations/")) payload = { session_id: "voice-browser", messages: [] };
        else if (request.path === "/tasks") payload = { tasks: [] };
        else if (request.path.startsWith("/memory?")) payload = { memories: [] };
        else if (request.path.startsWith("/intelligence/items")) payload = [];
        else if (request.path.startsWith("/intelligence/briefs")) payload = [];
        else if (request.path === "/intelligence/maintenance") payload = [];
        else if (request.path === "/voice/sessions" && request.method === "POST") payload = { id: "voice-session", session_id: body.session_id, state: "idle", language: "tr", generation: 0, interaction_id: null, last_user_utterance: null, last_assistant_utterance: null, error: null, created_at: "2026-09-18T00:00:00Z", updated_at: "2026-09-18T00:00:00Z" };
        else if (request.path === "/chat") {
          state.__chatBodies!.push(body);
          payload = { response: state.__chatBodies!.length === 1 ? "Sistem dengeli." : "VS Code acik.", session_id: body.session_id, provider: "windows-agent", mode: "private", intent: "unknown" };
        }
        return { status: 200, statusText: "OK", headers: { "content-type": "application/json" }, body: encode(payload) };
      } },
      agent: { status: async () => ({ status: "online" }), execute: async () => ({ ok: true, data: {
        cpu: { usage_percent: 12 }, memory: { total_bytes: 34359738368, available_bytes: 21474836480 }, disk: { usage_percent: 44 }, uptime_seconds: 7200, network_online: true,
        gpu: { devices: [{ name: "NVIDIA RTX 4080 SUPER", usage_percent: 7, temperature_c: 43, memory_used_mb: 1240, memory_total_mb: 16384 }] },
      } }) },
      voice: {
        status: async () => ({ engine: "local-whisper", available: true }),
        listen: async () => {
          listenCount += 1;
          if (listenCount === 1) return { transcript: "Bilgisayarın durumunu söyle.", language: "tr", engine: "local-whisper", device: "cuda" };
          return new Promise((resolve) => { state.__resolveBarge = resolve; });
        },
        stop: async () => true,
        onState: (callback) => { state.__voiceStateCallback = callback; return () => { state.__voiceStateCallback = undefined; }; },
        live: {
          available: async () => false,
          start: async () => ({ started: false }),
          stop: async () => true,
          interrupt: async () => true,
          sendText: async () => true,
          onEvent: () => () => undefined,
        },
      },
      shell: { showDataFolder: async () => true, openExternal: async () => true },
    };
  });
  await page.goto("/");
  await expect(page.locator(".desktop-command-center")).toBeVisible();
  await expect(page.locator(".sidebar")).toHaveCount(0);
  await expect(page.locator(".core-character")).toBeVisible();
  await expect.poll(() => page.locator(".core-character").evaluate((image) => (image as HTMLImageElement).naturalWidth)).toBeGreaterThan(1000);
  await page.locator(".desktop-nav-rail").getByRole("button", { name: "Oluştur" }).click();
  await expect(page.getByRole("heading", { name: /Fikri yüzeye çıkar/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.locator(".desktop-nav-rail").getByRole("button", { name: "Sohbet" }).click();
  await expect(page.getByRole("heading", { name: "Conversation" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "AKASHI ile konuş" })).toBeEnabled();
  await page.getByRole("button", { name: "AKASHI ile konuş" }).click();
  await expect(page.getByText(/Sistem dengeli\./)).toBeVisible();
  await expect(page.locator(".system-instrument")).toBeVisible();
  await expect(page.locator(".system-instrument")).toContainText("43°C");
  await expect.poll(() => page.evaluate(() => Boolean((window as typeof window & { __resolveBarge?: unknown }).__resolveBarge))).toBe(true);

  const latency = await page.evaluate(() => {
    const state = window as typeof window & {
      __speechCancelledAt?: number;
      __resolveBarge?: (value: { transcript: string; language: string; engine: string; device: string }) => void;
      __voiceStateCallback?: (value: { state: "speech_started"; detectedAtMs: number }) => void;
    };
    const detectedAt = Date.now();
    state.__voiceStateCallback?.({ state: "speech_started", detectedAtMs: detectedAt });
    state.__resolveBarge?.({ transcript: "VS Code'u aç.", language: "tr", engine: "local-whisper", device: "cuda" });
    return (state.__speechCancelledAt ?? detectedAt + 10_000) - detectedAt;
  });
  expect(latency).toBeLessThan(100);
  await expect(page.getByText(/VS Code acik\./)).toBeVisible();
  const chatBodies = await page.evaluate(() => (window as typeof window & { __chatBodies?: Array<Record<string, unknown>> }).__chatBodies);
  const overlapCount = await page.evaluate(() => (window as typeof window & { __speechOverlapCount?: number }).__speechOverlapCount);
  expect(chatBodies).toHaveLength(2);
  expect(chatBodies?.[1]).toMatchObject({ message: "VS Code'u aç.", voice: true });
  expect(overlapCount).toBe(0);
});

test("desktop HUD module inventory: clean default, open/close, persistence, and one continuous energy spectrum", async ({ page }) => {
  test.setTimeout(60000);
  await page.addInitScript(() => {
    const encode = (value: unknown) => btoa(JSON.stringify(value));
    window.akashiDesktop = {
      platform: "win32",
      config: {
        load: async () => ({ baseUrl: "http://127.0.0.1:8000", tokenStored: true }),
        save: async (value) => ({ baseUrl: value.baseUrl, tokenStored: true }),
      },
      provider: {
        load: async () => ({ aiProvider: "", geminiKeyStored: false, geminiModel: "" }),
        save: async () => ({ aiProvider: "", geminiKeyStored: false, geminiModel: "" }),
      },
      windowControls: {
        minimize: async () => true,
        maximize: async () => false,
        close: async () => true,
        isMaximized: async () => false,
        onState: () => () => undefined,
      },
      runtime: {
        status: async () => ({ overall: "READY", coreMode: "local", updatedAt: new Date().toISOString(), components: {
          core: { state: "READY", detail: "Core ready", pid: 1, owned: true, restartCount: 0 },
          agent: { state: "READY", detail: "Body ready", pid: 2, owned: true, restartCount: 0 },
          ollama: { state: "READY", detail: "Ollama ready", pid: null, owned: false, restartCount: 0 },
          comfyui: { state: "OFFLINE", detail: "ComfyUI offline", pid: null, owned: false, restartCount: 0 },
          voice: { state: "READY", detail: "Whisper ready", pid: null, owned: false, restartCount: 0 },
        } }),
        whenReady: async () => null,
        recover: async () => { throw new Error("not used"); },
        onState: () => () => undefined,
      },
      api: { fetch: async (request) => {
        let payload: unknown = { status: "ok" };
        if (request.path === "/system/capabilities") payload = { models: Object.fromEntries(["fast", "quality", "reasoning", "vision"].map((name) => [name, { available: true, accepts_images: name === "vision", kind: "model" }])) };
        else if (request.path === "/system/health") payload = { core: { status: "online", detail: "Core" }, auth: { status: "authorized", detail: "Auth" }, model: { status: "online", detail: "Model" }, ollama: { status: "online", detail: "Ollama" }, images: { status: "offline", detail: "Images" }, research: { status: "configured", detail: "Research" }, desktop_agent: { status: "online", detail: "Desktop", online: 1, paired: 1 } };
        else if (request.path.startsWith("/memory/conversations?")) payload = { conversations: [] };
        else if (request.path.startsWith("/memory/conversations/")) payload = { session_id: "hud-browser", messages: [] };
        else if (request.path === "/tasks") payload = { tasks: [{ id: "task-1", title: "Research the release notes", status: "running", progress: 40, approved: true, steps: [{ id: "step-1", tool: "research.web", risk: "safe", status: "running", result: null, error: null }], result: null, error: null, created_at: "2026-09-18T00:00:00Z" }] };
        else if (request.path.startsWith("/memory?")) payload = { memories: [] };
        else if (request.path === "/files") payload = { files: [] };
        else if (request.path === "/devices") payload = { devices: [] };
        else if (request.path.startsWith("/intelligence/items")) payload = [];
        else if (request.path.startsWith("/intelligence/briefs")) payload = [];
        else if (request.path === "/intelligence/maintenance") payload = [];
        return { status: 200, statusText: "OK", headers: { "content-type": "application/json" }, body: encode(payload) };
      } },
      agent: {
        status: async () => ({ status: "online" }),
        execute: async (action: string) => {
          if (action === "list_processes") return { ok: true, data: { processes: [{ pid: 111, name: "akashi-core.exe", status: "running", memory_percent: 4.2 }] } };
          return { ok: true, data: {
            cpu: { usage_percent: 12 }, memory: { total_bytes: 34359738368, available_bytes: 21474836480 }, disk: { usage_percent: 44 }, uptime_seconds: 7200, network_online: true,
            gpu: { devices: [{ name: "NVIDIA RTX 4080 SUPER", usage_percent: 7, temperature_c: 43, memory_used_mb: 1240, memory_total_mb: 16384 }] },
          } };
        },
      },
      voice: {
        status: async () => ({ engine: "local-whisper", available: true }),
        listen: () => new Promise(() => undefined),
        stop: async () => true,
        onState: () => () => undefined,
        live: {
          available: async () => false,
          start: async () => ({ started: false }),
          stop: async () => true,
          interrupt: async () => true,
          sendText: async () => true,
          onEvent: () => () => undefined,
        },
      },
      shell: { showDataFolder: async () => true, openExternal: async () => true },
    };
  });
  await page.goto("/");
  await expect(page.locator(".desktop-command-center")).toBeVisible();

  // Clean default: no dashboard clutter - only Activity and the floating Core
  // Telemetry (SYS MONITOR) card are on by default, matching the reference HUD.
  await expect(page.locator(".hud-module")).toHaveCount(0);
  await expect(page.locator(".activity-instrument")).toBeVisible();
  await expect(page.locator(".system-instrument")).toBeVisible();
  await page.getByRole("button", { name: "Agent Dock", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Agent Dock" })).toBeVisible();
  await expect(page.locator(".agent-dock")).toContainText("Research the release notes");
  await page.keyboard.press("Escape");

  // Open the Module Inventory toolbox and enable Sensors, Tasks, Data Streams.
  await page.locator(".hud-inventory-toggle").click();
  await expect(page.getByText("MODULE INVENTORY")).toBeVisible();
  const inventory = page.locator(".hud-inventory-panel");
  await inventory.getByRole("button", { name: /^Sensors/ }).click();
  await inventory.getByRole("button", { name: /^Tasks/ }).click();
  await inventory.getByRole("button", { name: /^Data Streams/ }).click();
  await expect(page.locator(".hud-module")).toHaveCount(5);
  await expect(page.locator(".hud-module-heading strong", { hasText: "Sensors" })).toBeVisible();
  await expect(page.locator(".hud-module-heading strong", { hasText: "Tasks" })).toBeVisible();
  await expect(page.locator(".hud-module-heading strong", { hasText: "Data Streams" })).toBeVisible();

  // The Tasks module shows the real (mocked) queue - no invented data.
  await expect(page.locator(".hud-task-list").getByText("Research the release notes")).toBeVisible();

  // Disable Sensors again from the same inventory.
  await inventory.getByRole("button", { name: /^Sensors/ }).click();
  await expect(page.locator(".hud-module")).toHaveCount(4);
  await expect(page.locator(".hud-module-heading strong", { hasText: "Sensors" })).toHaveCount(0);
  await page.locator(".hud-inventory-toggle").click();

  // Relaunch: the enabled-module selection must survive a reload.
  await page.reload();
  await expect(page.locator(".desktop-command-center")).toBeVisible();
  await page.locator(".hud-inventory-toggle").click();
  await expect(page.locator(".hud-module")).toHaveCount(4);
  await expect(page.locator(".hud-module-heading strong", { hasText: "Tasks" })).toBeVisible();
  await expect(page.locator(".hud-module-heading strong", { hasText: "Data Streams" })).toBeVisible();
  await expect(page.locator(".hud-module-heading strong", { hasText: "Sensors" })).toHaveCount(0);

  // CALM -> BEST OF BEST -> HARDCARRY ramp through one continuous OKLCH energy
  await page.keyboard.press("Escape");
  // spectrum (rising --ak-energy, rising rendered --ak-red saturation), not three
  // unrelated theme swaps, and the same value drives HUD module chrome too.
  // --ak-energy ramps over a multi-second CSS transition, so wait for it to settle
  // on its new target (rather than sampling a value mid-interpolation) before reading.
  async function waitForStableEnergy() {
    await page.evaluate(() => { (window as typeof window & { __lastEnergy?: number }).__lastEnergy = undefined; });
    await page.waitForFunction(() => {
      const element = document.querySelector(".desktop-command-center")!;
      const current = Number(getComputedStyle(element).getPropertyValue("--ak-energy"));
      const state = window as typeof window & { __lastEnergy?: number };
      const stable = state.__lastEnergy === current;
      state.__lastEnergy = current;
      return stable;
    }, undefined, { timeout: 8000, polling: 150 });
  }
  const readEnergy = () => page.locator(".desktop-command-center").evaluate((element) => Number(getComputedStyle(element).getPropertyValue("--ak-energy")));
  const readRed = () => page.locator(".desktop-command-center").evaluate((element) => getComputedStyle(element).getPropertyValue("--ak-red"));

  await page.getByRole("button", { name: "CALM" }).click();
  await expect(page.locator(".desktop-command-center")).toHaveAttribute("data-mood", "calm");
  await waitForStableEnergy();
  const calmEnergy = await readEnergy();
  const calmRed = await readRed();

  await page.getByRole("button", { name: "BEST OF BEST" }).click();
  await expect(page.locator(".desktop-command-center")).toHaveAttribute("data-mood", "best");
  await waitForStableEnergy();
  const bestEnergy = await readEnergy();

  await page.getByRole("button", { name: "HARDCARRY" }).click();
  await expect(page.locator(".desktop-command-center")).toHaveAttribute("data-mood", "hardcarry");
  await waitForStableEnergy();
  const hardcarryEnergy = await readEnergy();
  const hardcarryRed = await readRed();

  expect(calmEnergy).toBeLessThan(bestEnergy);
  expect(bestEnergy).toBeLessThan(hardcarryEnergy);
  expect(calmRed).not.toBe(hardcarryRed);
});
