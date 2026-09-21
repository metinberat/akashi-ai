const {
  app,
  dialog,
  BrowserWindow,
  ipcMain,
  Menu,
  net,
  protocol,
  safeStorage,
  session,
  shell,
} = require("electron");
const fs = require("node:fs");
const crypto = require("node:crypto");
const { spawn } = require("node:child_process");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { validateSender, validateApiPath, readBoundedBody, validateVoiceOptions } = require("./security.cjs");
const { DesktopRuntimeSupervisor, boundedEnvironment, discoverPython } = require("./runtime-supervisor.cjs");

protocol.registerSchemesAsPrivileged([
  {
    scheme: "akashi",
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: true,
      stream: true,
    },
  },
]);

const ALLOWED_METHODS = new Set(["GET", "POST", "PATCH", "DELETE", "OPTIONS"]);
const LOCAL_AGENT_ACTIONS = new Set([
  "get_system_status", "list_processes", "application_status", "list_directory",
  "find_file", "file_metadata", "launch_application", "open_project", "reveal_file",
  "take_screenshot", "capture_camera_frame", "run_project_script",
]);
const LOCAL_CONFIRM_ACTIONS = new Set([
  "launch_application", "open_project", "reveal_file", "take_screenshot",
  "capture_camera_frame", "run_project_script",
]);
const DATA_FILE = "connection.secure";
const RUNTIME_SECRET_FILE = "runtime.secure";
const PROVIDER_FILE = "provider.secure";
const PROVIDER_ALLOWED = new Set(["ollama", "gemini", "mock"]);
let activeVoiceProcess = null;
let activeLiveVoiceProcess = null;
let runtimeSupervisor = null;
let mainWindow = null;
let shutdownStarted = false;

function voiceCommand() {
  return { executable: discoverPython("AKASHI_VOICE_PYTHON"), prefix: [] };
}

function voiceScriptPath() {
  return app.isPackaged
    ? path.join(process.resourcesPath, "voice", "listen.py")
    : path.resolve(__dirname, "voice", "listen.py");
}

function runVoice(args, sender, active) {
  const command = voiceCommand();
  const script = voiceScriptPath();
  if (!fs.existsSync(script)) throw new Error("Desktop voice worker is missing.");
  return new Promise((resolve, reject) => {
    const child = spawn(command.executable, [...command.prefix, script, ...args], {
      cwd: path.dirname(script),
      env: boundedEnvironment({ PYTHONIOENCODING: "utf-8" }),
      windowsHide: true, shell: false, stdio: ["ignore", "pipe", "pipe"],
    });
    if (active) activeVoiceProcess = child;
    let output = "";
    let errors = "";
    let settled = false;
    const timeout = setTimeout(() => {
      child.kill();
      if (!settled) { settled = true; reject(new Error("Desktop speech recognition timed out.")); }
    }, active ? 90000 : 15000);
    const finish = (error, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      if (activeVoiceProcess === child) activeVoiceProcess = null;
      error ? reject(error) : resolve(value);
    };
    child.on("error", (error) => finish(new Error("Local Whisper could not start.", { cause: error })));
    child.stderr.on("data", (chunk) => { errors = (errors + chunk.toString("utf8")).slice(-8000); });
    child.stdout.on("data", (chunk) => {
      output += chunk.toString("utf8");
      if (output.length > 64000) { child.kill(); finish(new Error("Voice worker output exceeded its safety limit.")); return; }
      const lines = output.split(/\r?\n/u);
      output = lines.pop() || "";
      for (const line of lines) {
        if (!line.trim()) continue;
        let event;
        try { event = JSON.parse(line); } catch { continue; }
        if (event.event === "state" && sender && !sender.isDestroyed()) {
          const allowedStates = new Set(["listening", "speech_started", "transcribing"]);
          if (allowedStates.has(event.state)) {
            sender.send("akashi:voice:state", {
              state: event.state,
              detectedAtMs: Number.isFinite(event.detected_at_ms) ? event.detected_at_ms : undefined,
            });
          }
        }
        if (event.event === "result") {
          if (event.ok) finish(null, event);
          else finish(new Error(String(event.message || event.code || "Speech recognition failed.")));
        }
      }
    });
    child.on("close", (code) => {
      if (!settled) finish(new Error(errors.trim() || `Voice worker stopped (${code}).`));
    });
  });
}

function liveVoiceScriptPath() {
  return app.isPackaged
    ? path.join(process.resourcesPath, "voice", "absolute_live.py")
    : path.resolve(__dirname, "voice", "absolute_live.py");
}

const FALLBACK_VOICE_PERSONA = {
  identity: "Name: AKASHI\nRole: A composed, decisive AI assistant, exact about uncertainty.",
  voice_style: "Keep voice replies brief, direct and speakable.",
};

async function fetchVoicePersona(config) {
  if (!config.baseUrl) return FALLBACK_VOICE_PERSONA;
  try {
    const response = await fetch(`${config.baseUrl.replace(/\/+$/u, "")}/system/voice-persona`, {
      headers: config.token ? { Authorization: `Bearer ${config.token}` } : {},
      signal: AbortSignal.timeout(4000),
    });
    if (!response.ok) return FALLBACK_VOICE_PERSONA;
    const data = await response.json();
    return {
      identity: typeof data.identity === "string" ? data.identity : FALLBACK_VOICE_PERSONA.identity,
      voice_style: typeof data.voice_style === "string" ? data.voice_style : FALLBACK_VOICE_PERSONA.voice_style,
    };
  } catch {
    return FALLBACK_VOICE_PERSONA;
  }
}

async function startLiveVoice(sender, options) {
  if (activeLiveVoiceProcess) return { started: true, alreadyRunning: true };
  const script = liveVoiceScriptPath();
  if (!fs.existsSync(script)) throw new Error("Desktop live voice worker is missing.");
  const provider = readProviderConfig();
  if (!provider.geminiApiKey) throw new Error("Configure a Gemini API key first.");
  const backendConfig = readSecureConfig();
  const persona = await fetchVoicePersona(backendConfig);

  const devPython = path.resolve(
  __dirname,
  "..",
  "..",
  "backend",
  ".venv",
  "Scripts",
  "python.exe"
);

const command = !app.isPackaged && fs.existsSync(devPython)
  ? { executable: devPython, prefix: [] }
  : voiceCommand();
  const child = spawn(command.executable, [...command.prefix, script], {
    cwd: path.dirname(script),
    env: boundedEnvironment({ PYTHONIOENCODING: "utf-8" }),
    windowsHide: true, shell: false, stdio: ["pipe", "pipe", "pipe"],
  });
  activeLiveVoiceProcess = child;

  const handshake = {
    gemini_api_key: provider.geminiApiKey,
    core_base_url: backendConfig.baseUrl || "",
    core_token: backendConfig.token || "",
    voice_name: "Charon",
    language: options && typeof options.language === "string" ? options.language : "auto",
    identity: persona.identity,
    voice_style: persona.voice_style,
  };
  try {
    child.stdin.write(`${JSON.stringify(handshake)}\n`);
  } catch (error) {
    child.kill();
    activeLiveVoiceProcess = null;
    throw new Error("Could not start the live voice worker.", { cause: error });
  }

  let buffer = "";
  const forward = (chunk) => {
    buffer = (buffer + chunk.toString("utf8")).slice(-64_000);
    const lines = buffer.split(/\r?\n/u);
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (!line.trim()) continue;
      let event;
      try { event = JSON.parse(line); } catch { continue; }
      if (sender && !sender.isDestroyed()) sender.send("akashi:voice:live:event", event);
    }
  };
  child.stdout.on("data", forward);
  child.stderr.on("data", (chunk) => {
  console.error("[AKASHI LIVE]", chunk.toString("utf8"));
  });
  child.on("error", () => {
    if (activeLiveVoiceProcess === child) activeLiveVoiceProcess = null;
    if (sender && !sender.isDestroyed()) {
      sender.send("akashi:voice:live:event", { event: "error", message: "voice_worker_failed" });
    }
  });
  child.on("close", () => {
    if (activeLiveVoiceProcess === child) activeLiveVoiceProcess = null;
    if (sender && !sender.isDestroyed()) {
      sender.send("akashi:voice:live:event", { event: "state", state: "idle" });
    }
  });
  return { started: true, alreadyRunning: false };
}

function stopLiveVoice() {
  if (!activeLiveVoiceProcess) return false;
  const child = activeLiveVoiceProcess;
  try { child.stdin.write(`${JSON.stringify({ cmd: "stop" })}\n`); } catch { /* already closing */ }
  setTimeout(() => { try { child.kill(); } catch { /* already exited */ } }, 2500);
  return true;
}

function interruptLiveVoice() {
  if (!activeLiveVoiceProcess) return false;
  try {
    activeLiveVoiceProcess.stdin.write(`${JSON.stringify({ cmd: "interrupt" })}\n`);
    return true;
  } catch {
    return false;
  }
}

function sendLiveVoiceText(text) {
  if (!activeLiveVoiceProcess) return false;
  try {
    activeLiveVoiceProcess.stdin.write(`${JSON.stringify({ cmd: "text", text: String(text).slice(0, 4000) })}\n`);
    return true;
  } catch {
    return false;
  }
}

function validateBackendUrl(value) {
  const input = String(value || "").trim();
  if (!input) return "";
  let url;
  try {
    url = new URL(input);
  } catch {
    throw new Error("Invalid backend URL.");
  }
  if (url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new Error("Enter only the backend origin without credentials or a path.");
  }
  if (url.protocol === "https:") return url.origin;
  if (url.protocol !== "http:" || !isPrivateHost(url.hostname)) {
    throw new Error("Desktop HTTP is limited to loopback or private LAN addresses; otherwise use HTTPS.");
  }
  return url.origin;
}

function isPrivateHost(hostname) {
  const host = hostname.replace(/^\[|\]$/g, "").toLowerCase();
  if (host === "localhost" || host === "::1" || host === "127.0.0.1") return true;
  const match = host.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (!match) return false;
  const octets = match.slice(1).map(Number);
  if (octets.some((value) => value > 255)) return false;
  return octets[0] === 10 || octets[0] === 127 ||
    (octets[0] === 192 && octets[1] === 168) ||
    (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31);
}

function isLoopbackHost(hostname) {
  const host = hostname.replace(/^\[|\]$/g, "").toLowerCase();
  return host === "localhost" || host === "::1" || host === "127.0.0.1";
}

function configPath() {
  return path.join(app.getPath("userData"), DATA_FILE);
}

function normalizeCoreMode(value, baseUrl) {
  if (value === "local" || value === "remote") return value;
  return baseUrl && isLoopbackHost(new URL(baseUrl).hostname) ? "local" : "remote";
}

function readSecureConfig() {
  const filename = configPath();
  if (!fs.existsSync(filename)) {
    const mode = process.env.AKASHI_DESKTOP_CORE_MODE === "remote" ? "remote" : "local";
    const localUrl = validateBackendUrl(process.env.AKASHI_DESKTOP_CORE_URL || "http://127.0.0.1:8000");
    if (mode === "local" && !isLoopbackHost(new URL(localUrl).hostname)) {
      throw new Error("AKASHI_DESKTOP_CORE_URL must use loopback in Local Core mode.");
    }
    return { baseUrl: mode === "local" ? localUrl : "", token: "", coreMode: mode };
  }
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error("Windows secure storage is unavailable.");
  }
  try {
    const plaintext = safeStorage.decryptString(fs.readFileSync(filename));
    const value = JSON.parse(plaintext);
    const baseUrl = validateBackendUrl(value.baseUrl);
    return {
      baseUrl,
      token: typeof value.token === "string" ? value.token : "",
      coreMode: normalizeCoreMode(value.coreMode, baseUrl),
    };
  } catch (error) {
    throw new Error("AKASHI could not read its encrypted connection settings.", { cause: error });
  }
}

function writeSecureConfig(value) {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error("Windows secure storage is unavailable.");
  }
  const current = readSecureConfig();
  const coreMode = value.coreMode === "local" || value.coreMode === "remote"
    ? value.coreMode : current.coreMode;
  const baseUrl = validateBackendUrl(value.baseUrl || (coreMode === "local" ? "http://127.0.0.1:8000" : ""));
  if (coreMode === "local") {
    const parsedBaseUrl = new URL(baseUrl);
    if (!isLoopbackHost(parsedBaseUrl.hostname) || !parsedBaseUrl.port || Number(parsedBaseUrl.port) < 1024) {
      throw new Error("Local Core mode requires a loopback backend origin with an explicit unprivileged port.");
    }
  }
  let token = typeof value.token === "string" ? value.token.trim() : baseUrl === current.baseUrl ? current.token : "";
  if (coreMode === "local" && token.length < 32) token = crypto.randomBytes(36).toString("base64url");
  const output = { baseUrl, token, coreMode };
  fs.mkdirSync(app.getPath("userData"), { recursive: true });
  fs.writeFileSync(configPath(), safeStorage.encryptString(JSON.stringify(output)));
  return { baseUrl, tokenStored: Boolean(token), coreMode };
}

function ensureDesktopConfig() {
  const config = readSecureConfig();
  if (config.coreMode === "local" && (!config.baseUrl || config.token.length < 32)) {
    writeSecureConfig({
      baseUrl: config.baseUrl || "http://127.0.0.1:8000",
      coreMode: "local",
      token: config.token,
    });
  }
  return readSecureConfig();
}

function providerConfigPath() {
  return path.join(app.getPath("userData"), PROVIDER_FILE);
}

function readProviderConfig() {
  const filename = providerConfigPath();
  if (!fs.existsSync(filename)) return { aiProvider: "", geminiApiKey: "", geminiModel: "" };
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error("Windows secure storage is unavailable.");
  }
  try {
    const value = JSON.parse(safeStorage.decryptString(fs.readFileSync(filename)));
    return {
      aiProvider: PROVIDER_ALLOWED.has(value.aiProvider) ? value.aiProvider : "",
      geminiApiKey: typeof value.geminiApiKey === "string" ? value.geminiApiKey : "",
      geminiModel: typeof value.geminiModel === "string" ? value.geminiModel.slice(0, 200) : "",
    };
  } catch (error) {
    throw new Error("AKASHI could not read its encrypted provider settings.", { cause: error });
  }
}

function writeProviderConfig(value) {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error("Windows secure storage is unavailable.");
  }
  const current = readProviderConfig();
  const aiProvider = PROVIDER_ALLOWED.has(value?.aiProvider) ? value.aiProvider : current.aiProvider;
  const geminiApiKey = typeof value?.geminiApiKey === "string" ? value.geminiApiKey.trim().slice(0, 4096) : current.geminiApiKey;
  const geminiModel = typeof value?.geminiModel === "string" ? value.geminiModel.trim().slice(0, 200) : current.geminiModel;
  const output = { aiProvider, geminiApiKey, geminiModel };
  fs.mkdirSync(app.getPath("userData"), { recursive: true });
  fs.writeFileSync(providerConfigPath(), safeStorage.encryptString(JSON.stringify(output)));
  return { aiProvider, geminiKeyStored: Boolean(geminiApiKey), geminiModel };
}

function parseDotEnv(text) {
  const values = {};
  for (const rawLine of text.split(/\r?\n/u)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/u);
    if (!match) continue;
    let value = match[2].trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    values[match[1]] = value;
  }
  return values;
}

function migrateProviderConfigFromEnv() {
  if (app.isPackaged || fs.existsSync(providerConfigPath())) return;
  const envPath = path.resolve(__dirname, "..", "..", "backend", ".env");
  if (!fs.existsSync(envPath)) return;
  try {
    const values = parseDotEnv(fs.readFileSync(envPath, "utf8"));
    if (!values.AI_PROVIDER && !values.GEMINI_API_KEY) return;
    writeProviderConfig({
      aiProvider: (values.AI_PROVIDER || "").trim().toLowerCase(),
      geminiApiKey: values.GEMINI_API_KEY || "",
      geminiModel: values.GEMINI_MODEL || "",
    });
    runtimeSupervisor?.logger?.write("core", "provider_migrated_from_env", {});
  } catch {
    // Best-effort: a failed migration just leaves provider.secure unset; the user can configure it in Settings.
  }
}

function runtimeSecretPath() {
  return path.join(app.getPath("userData"), RUNTIME_SECRET_FILE);
}

function ensureAgentToken() {
  const configured = String(process.env.AKASHI_AGENT_TOKEN || "").trim();
  if (configured.length >= 32) return configured;
  if (!safeStorage.isEncryptionAvailable()) throw new Error("Windows secure storage is unavailable.");
  const filename = runtimeSecretPath();
  if (fs.existsSync(filename)) {
    try {
      const value = JSON.parse(safeStorage.decryptString(fs.readFileSync(filename)));
      if (typeof value.agentToken === "string" && value.agentToken.length >= 32) return value.agentToken;
    } catch (error) {
      throw new Error("AKASHI could not read its encrypted runtime credential.", { cause: error });
    }
  }
  const agentToken = crypto.randomBytes(36).toString("base64url");
  fs.mkdirSync(app.getPath("userData"), { recursive: true });
  fs.writeFileSync(filename, safeStorage.encryptString(JSON.stringify({ agentToken })));
  return agentToken;
}

function decodeBody(body) {
  if (JSON.stringify(body || {}).length > 30 * 1024 * 1024) throw new Error("Upload exceeds the desktop safety limit.");
  if (!body || body.kind === "none") return undefined;
  if (body.kind === "text") return String(body.value || "");
  if (body.kind === "base64") return Buffer.from(body.value || "", "base64");
  if (body.kind === "form") {
    const form = new FormData();
    for (const entry of body.entries || []) {
      if (entry.kind === "file") {
        form.append(
          entry.name,
          new Blob([Buffer.from(entry.value || "", "base64")], { type: entry.type || "application/octet-stream" }),
          entry.filename || "upload.bin",
        );
      } else {
        form.append(entry.name, String(entry.value || ""));
      }
    }
    return form;
  }
  throw new Error("Unsupported request body.");
}

function registerIpc() {
  const handle = (channel, callback) => ipcMain.handle(channel, (event, ...args) => {
    validateSender(event);
    return callback(event, ...args);
  });
  handle("akashi:config:load", () => {
    const value = readSecureConfig();
    return { baseUrl: value.baseUrl, tokenStored: Boolean(value.token), coreMode: value.coreMode };
  });
  handle("akashi:config:save", (_event, value) => {
    const saved = writeSecureConfig(value || {});
    if (runtimeSupervisor) void runtimeSupervisor.reconfigure();
    return saved;
  });
  handle("akashi:provider:load", () => {
    const value = readProviderConfig();
    return { aiProvider: value.aiProvider, geminiKeyStored: Boolean(value.geminiApiKey), geminiModel: value.geminiModel };
  });
  handle("akashi:provider:save", (_event, value) => {
    const saved = writeProviderConfig(value || {});
    if (runtimeSupervisor) void runtimeSupervisor.reconfigure();
    return saved;
  });
  handle("akashi:window:minimize", (event) => {
    BrowserWindow.fromWebContents(event.sender)?.minimize();
    return true;
  });
  handle("akashi:window:maximize", (event) => {
    const window = BrowserWindow.fromWebContents(event.sender);
    if (!window) return false;
    if (window.isMaximized()) window.unmaximize();
    else window.maximize();
    return window.isMaximized();
  });
  handle("akashi:window:close", (event) => {
    BrowserWindow.fromWebContents(event.sender)?.close();
    return true;
  });
  handle("akashi:window:is-maximized", (event) => Boolean(BrowserWindow.fromWebContents(event.sender)?.isMaximized()));
  handle("akashi:runtime:status", () => runtimeSupervisor?.status() || null);
  handle("akashi:runtime:ready", async () => runtimeSupervisor ? runtimeSupervisor.whenReady() : null);
  handle("akashi:runtime:recover", async (_event, component) => {
    if (!runtimeSupervisor) throw new Error("Desktop runtime is unavailable.");
    return runtimeSupervisor.recover(String(component || ""));
  });
  handle("akashi:shell:data-folder", async () => {
    await shell.openPath(app.getPath("userData"));
    return true;
  });
  handle("akashi:shell:open-external", async (_event, value) => {
    const url = new URL(String(value || ""));
    if (!["https:", "http:"].includes(url.protocol) || url.username || url.password) throw new Error("External URL is not allowed.");
    await shell.openExternal(url.toString());
    return true;
  });
  handle("akashi:agent:status", async () => {
    const supervised = runtimeSupervisor?.status()?.components?.agent;
    if (supervised) return { status: supervised.state === "READY" ? "ok" : "offline", runtime: supervised };
    const port = Math.max(1024, Math.min(Number(process.env.AKASHI_AGENT_PORT || 8765), 65535));
    try {
      const response = await fetch(`http://127.0.0.1:${port}/health`, { redirect: "error", signal: AbortSignal.timeout(2500) });
      return response.ok ? await response.json() : { status: "offline" };
    } catch {
      return { status: "offline" };
    }
  });
  handle("akashi:agent:execute", async (_event, request) => {
    const action = String(request?.action || "");
    if (!LOCAL_AGENT_ACTIONS.has(action)) throw new Error("Unsupported local action.");
    const approved = request?.approved === true;
    if (LOCAL_CONFIRM_ACTIONS.has(action) && !approved) throw new Error("This local action requires approval.");
    if (JSON.stringify(request).length > 64_000) throw new Error("Action arguments exceed the limit.");
    if (LOCAL_CONFIRM_ACTIONS.has(action)) {
      const choice = await dialog.showMessageBox(BrowserWindow.fromWebContents(_event.sender), {
        type: "warning", title: "AKASHI · Confirm local action", message: action,
        detail: JSON.stringify(request.arguments || {}, null, 2).slice(0, 4000),
        buttons: ["Cancel", "Execute"], defaultId: 0, cancelId: 0, noLink: true,
      });
      if (choice.response !== 1) throw new Error("Local action cancelled.");
    }
    const token = ensureAgentToken();
    if (token.length < 32) throw new Error("AKASHI_AGENT_TOKEN is not configured for Desktop.");
    const port = Math.max(1024, Math.min(Number(process.env.AKASHI_AGENT_PORT || 8765), 65535));
    const response = await fetch(`http://127.0.0.1:${port}/v1/actions/execute`, {
      method: "POST",
      redirect: "error",
      headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        action,
        arguments: request?.arguments && typeof request.arguments === "object" ? request.arguments : {},
        approved,
      }),
      signal: AbortSignal.timeout(305_000),
    });
    if (!response.ok) throw new Error(`Local agent action failed (${response.status}).`);
    return JSON.parse((await readBoundedBody(response, 3 * 1024 * 1024)).toString("utf8"));
  });
  handle("akashi:voice:status", async (_event) => runVoice(["--probe"], _event.sender, false));
  handle("akashi:voice:listen", async (_event, value) => {
    if (activeVoiceProcess) activeVoiceProcess.kill();
    const options = validateVoiceOptions(value);
    const args = ["--language", options.language, "--model", options.model];
    if (options.bargeIn) args.push("--barge-in");
    return runVoice(args, _event.sender, true);
  });
  handle("akashi:voice:stop", () => {
    if (activeVoiceProcess) activeVoiceProcess.kill();
    activeVoiceProcess = null;
    return true;
  });
  handle("akashi:voice:live:available", () => Boolean(readProviderConfig().geminiApiKey));
  handle("akashi:voice:live:start", async (_event, options) => startLiveVoice(_event.sender, validateVoiceOptions(options)));
  handle("akashi:voice:live:stop", () => stopLiveVoice());
  handle("akashi:voice:live:interrupt", () => interruptLiveVoice());
  handle("akashi:voice:live:text", (_event, value) => sendLiveVoiceText(value));
  handle("akashi:api:fetch", async (_event, request) => {
    const config = readSecureConfig();
    if (!config.baseUrl) throw new Error("Configure the FastAPI backend first.");
    const route = validateApiPath(request.path);
    const method = String(request.method || "GET").toUpperCase();
    if (!ALLOWED_METHODS.has(method)) throw new Error("HTTP method is not allowed.");
    const headers = new Headers();
    for (const [name, value] of Object.entries(request.headers || {})) {
      const lower = name.toLowerCase();
      if (["accept", "content-type"].includes(lower) && typeof value === "string") {
        headers.set(name, value);
      }
    }
    if (request.authenticated !== false) {
      if (!config.token) throw new Error("Configure the personal backend access token first.");
      headers.set("Authorization", `Bearer ${config.token}`);
    } else if (route !== "/health") {
      throw new Error("Only the health route may be requested without authentication.");
    }
    const body = decodeBody(request.body);
    if (request.body?.kind === "form") headers.delete("content-type");
    let response;
    try {
      response = await fetch(`${config.baseUrl}${route}`, {
        method,
        redirect: "error",
        headers,
        body,
        signal: AbortSignal.timeout(310_000),
      });
    } catch (error) {
      throw new Error("FastAPI backend is unavailable.", { cause: error });
    }
    const bytes = await readBoundedBody(response);
    return {
      status: response.status,
      statusText: response.statusText,
      headers: Object.fromEntries(response.headers.entries()),
      body: bytes.toString("base64"),
    };
  });
}

function installProtocol() {
  const webRoot = path.resolve(__dirname, "web");
  protocol.handle("akashi", (request) => {
    const url = new URL(request.url);
    if (url.hostname !== "app") return new Response("Not found", { status: 404 });
    const pathname = decodeURIComponent(url.pathname === "/" ? "/index.html" : url.pathname);
    const requested = path.resolve(webRoot, `.${pathname}`);
    if (requested !== webRoot && !requested.startsWith(`${webRoot}${path.sep}`)) {
      return new Response("Forbidden", { status: 403 });
    }
    if (!fs.existsSync(requested) || !fs.statSync(requested).isFile()) {
      return new Response("Not found", { status: 404 });
    }
    return net.fetch(pathToFileURL(requested).toString());
  });
}

function createWindow() {
  const window = new BrowserWindow({
    title: "AKASHİ ABSOLUTE",
    width: 1440,
    height: 920,
    minWidth: 980,
    minHeight: 640,
    backgroundColor: "#030505",
    autoHideMenuBar: true,
    frame: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
    },
  });
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", (event, target) => {
    if (!target.startsWith("akashi://app/")) event.preventDefault();
  });
  const sendWindowState = () => {
    if (window.isDestroyed()) return;
    window.webContents.send("akashi:window:state", { maximized: window.isMaximized() });
  };
  window.on("maximize", sendWindowState);
  window.on("unmaximize", sendWindowState);
  window.loadURL("akashi://app/index.html");
 
  window.webContents.once("did-finish-load", () => {
    void startLiveVoice(window.webContents, { language: "auto" }).catch((error) => {
      console.error("[AKASHI LIVE AUTO START]", error);
    });
  });
  
  mainWindow = window;
  window.on("closed", () => { if (mainWindow === window) mainWindow = null; });
  return window;
}

function contentSecurityPolicy() {
  const index = path.resolve(__dirname, "web", "index.html");
  const html = fs.readFileSync(index, "utf8");
  const hashes = [];
  const scriptPattern = /<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/giu;
  for (const match of html.matchAll(scriptPattern)) {
    const digest = crypto.createHash("sha256").update(match[1], "utf8").digest("base64");
    hashes.push(`'sha256-${digest}'`);
  }
  return [
    "default-src 'self'",
    `script-src 'self' ${hashes.join(" ")}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' blob: data:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "frame-ancestors 'none'",
  ].join("; ");
}

const ownsApplicationInstance = app.requestSingleInstanceLock();

if (!ownsApplicationInstance) {
  app.quit();
} else {
  app.on("second-instance", () => {
    const window = mainWindow || BrowserWindow.getAllWindows()[0];
    if (!window) return;
    if (window.isMinimized()) window.restore();
    window.show();
    window.focus();
  });

  app.whenReady().then(() => {
    session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    session.defaultSession.setPermissionCheckHandler(() => false);
    Menu.setApplicationMenu(null);
    ensureDesktopConfig();
    ensureAgentToken();
    migrateProviderConfigFromEnv();
    const csp = contentSecurityPolicy();
    session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
      if (details.url.startsWith("akashi://app/")) {
        callback({
          responseHeaders: {
            ...details.responseHeaders,
            "Content-Security-Policy": [csp],
          },
        });
      } else {
        callback({ responseHeaders: details.responseHeaders });
      }
    });
    registerIpc();
    installProtocol();
    runtimeSupervisor = new DesktopRuntimeSupervisor({
      userData: app.getPath("userData"),
      resourcesPath: process.resourcesPath,
      appDirectory: __dirname,
      isPackaged: app.isPackaged,
      getConnectionConfig: readSecureConfig,
      getProviderEnv: readProviderConfig,
      getAgentToken: ensureAgentToken,
      probeVoice: () => runVoice(["--probe"], null, false),
      stopVoice: () => {
        if (activeVoiceProcess) activeVoiceProcess.kill();
        activeVoiceProcess = null;
        if (activeLiveVoiceProcess) activeLiveVoiceProcess.kill();
        activeLiveVoiceProcess = null;
      },
    });
    runtimeSupervisor.on("state", (state) => {
      for (const window of BrowserWindow.getAllWindows()) {
        if (!window.isDestroyed()) window.webContents.send("akashi:runtime:state", state);
      }
    });
    void runtimeSupervisor.start();
    createWindow();
    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });

  app.on("before-quit", (event) => {
    if (shutdownStarted) return;
    event.preventDefault();
    shutdownStarted = true;
    if (activeVoiceProcess) activeVoiceProcess.kill();
    activeVoiceProcess = null;
    if (activeLiveVoiceProcess) activeLiveVoiceProcess.kill();
    activeLiveVoiceProcess = null;
    const shutdown = runtimeSupervisor ? runtimeSupervisor.stop() : Promise.resolve();
    Promise.race([
      shutdown,
      new Promise((resolve) => setTimeout(resolve, 8000)),
    ]).finally(() => app.exit(0));
  });
}
