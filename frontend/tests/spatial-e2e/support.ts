// Shared helpers for the Spatial Lab and remote presence browser suites.
import type { Page } from "@playwright/test";

export const CORE = "http://127.0.0.1:8017";
export const TOKEN = "spatial-e2e-token-0000000000000000000000";
export const auth = { Authorization: `Bearer ${TOKEN}` };

/** Same contract as desktop/app/main.cjs akashi:api:fetch (token added outside the renderer), forwarding to the real Core. */
export async function desktopBridge(page: Page) {
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

