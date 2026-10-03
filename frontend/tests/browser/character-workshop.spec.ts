import { test, expect } from "@playwright/test";

test("desktop workshop is secondary, preserves source, shows measured scope and resumes checkpoints", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const errors: string[] = []; page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => {
    const encode = (value: unknown) => btoa(Array.from(new TextEncoder().encode(JSON.stringify(value)), byte => String.fromCharCode(byte)).join(""));
    const runtime = { overall: "READY", coreMode: "local", components: Object.fromEntries(["core", "agent", "voice", "ollama", "comfyui"].map(name => [name, { state: "READY" }])) };
    let job = { id: "improvement-fixture", asset_id: "character-fixture", status: "queued", attempts: 0, max_attempts: 8, synthetic: true, best_version: "source", baseline_version: "source" };
    window.akashiDesktop = {
      platform: "win32", config: { load: async () => ({ baseUrl: "https://api.example.test", tokenStored: true }) },
      provider: { load: async () => ({ aiProvider: "mock", geminiKeyStored: false, geminiModel: "" }) },
      runtime: { status: async () => runtime, whenReady: async () => runtime, onState: () => () => {} },
      windowControls: { isMaximized: async () => false, onState: () => () => {} },
      agent: { execute: async () => ({ ok: false }), status: async () => ({}) },
      voice: { status: async () => ({ available: false }), stop: async () => true, onState: () => () => {} },
      api: { fetch: async (request: { path: string; method: string }) => {
        let value: unknown = { status: "ok" };
        if (request.path === "/system/health") value = { core: { status: "online" }, auth: { status: "authorized" }, model: { status: "online" }, images: { status: "offline" }, research: { status: "configured" } };
        if (request.path === "/tasks" || request.path.startsWith("/autonomy/tasks")) value = { tasks: [] };
        if (request.path.startsWith("/events/recent")) value = { cursor: 0, events: [] };
        if (request.path.startsWith("/memory/conversations")) value = { conversations: [], messages: [] };
        if (request.path.startsWith("/memory?")) value = { memories: [] };
        if (request.path.startsWith("/intelligence/")) value = [];
        if (request.path.startsWith("/expertise/characters")) value = { characters: [{ id: "character-fixture", name: "SYNTHETIC UI FIXTURE", synthetic: 1, joint_count: 2, mesh_count: 1 }] };
        if (request.path === "/expertise/workshops") value = request.method === "POST" ? job : { workshops: [] };
        if (request.path.includes("/run?")) { job = { ...job, status: "paused", attempts: job.attempts+2, best_version: "best" }; value = job; }
        if (request.path.endsWith("/versions")) value = { versions: [{ id: "best", decision: { accepted: true, reasons: [] }, evaluation: { score: .123, scope: "numeric_tests_only", integrity: { defective_vertices: 0 }, deformation: { available: true } } }] };
        if (request.path.endsWith("/rollback")) { job = { ...job, best_version: "source" }; value = job; }
        return { status: 200, headers: { "content-type": "application/json" }, body: encode(value) };
      } },
    } as unknown as Window["akashiDesktop"];
  });
  await page.goto("/");
  await expect(page.locator(".desktop-core-stage")).toBeVisible();
  await expect(page.locator(".expertise-summary")).toHaveCount(0);
  await page.getByRole("button", { name: "Agent Dock", exact: true }).click();
  await page.getByRole("button", { name: "Autonomy Hub", exact: true }).click();
  const panel = page.getByRole("region", { name: "Character expertise" });
  await expect(panel).toContainText("SYNTHETIC UI FIXTURE");
  await panel.getByRole("button", { name: "Ölç / iyileştir" }).click();
  await expect(panel).toContainText("PAUSED");
  await expect(panel).toContainText("Sayısal skor: 0.123");
  await expect(panel).toContainText("Sanatsal/profesyonel kalite onayı değildir.");
  await panel.getByRole("button", { name: "Checkpoint’ten devam" }).click();
  await expect(panel).toContainText("4/8 bounded attempts");
  await panel.getByRole("button", { name: "Kaynak sürüme dön" }).click();
  await expect(panel.getByRole("button", { name: "Kaynak sürüme dön" })).toHaveCount(0);
  expect(errors).toEqual([]);
});
