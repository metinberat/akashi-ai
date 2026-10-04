const { EventEmitter } = require("node:events");
const fs = require("node:fs");
const path = require("node:path");
const { execFileSync, spawn, spawnSync } = require("node:child_process");

const STATES = new Set(["STARTING", "READY", "DEGRADED", "OFFLINE", "RECOVERING", "FAILED"]);
const LOG_LIMIT = 512 * 1024;
const RESTART_WINDOW_MS = 60_000;
const MAX_FAILURES = 3;

function boundedPort(value, fallback) {
  const parsed = Number(value || fallback);
  return Math.max(1024, Math.min(Number.isFinite(parsed) ? parsed : fallback, 65535));
}

function isLoopbackUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return ["localhost", "127.0.0.1", "::1", "[::1]"].includes(url.hostname.toLowerCase());
  } catch {
    return false;
  }
}

function redact(value) {
  return String(value || "")
    .replace(/\bBearer\s+[A-Za-z0-9._~+\/-]+/giu, "Bearer [REDACTED]")
    .replace(/(authorization|bearer|token|api[_-]?key|secret)(\s*[:=]?\s*)[^\s,;]+/giu, "$1$2[REDACTED]")
    .replace(/[A-Za-z0-9_-]{40,}/gu, "[REDACTED]")
    .slice(0, 500);
}

class RuntimeLogger {
  constructor(directory) {
    this.directory = directory;
    this.file = path.join(directory, "runtime.jsonl");
    fs.mkdirSync(directory, { recursive: true });
  }

  write(component, event, fields = {}) {
    try {
      if (fs.existsSync(this.file) && fs.statSync(this.file).size >= LOG_LIMIT) {
        const previous = `${this.file}.1`;
        fs.rmSync(previous, { force: true });
        fs.renameSync(this.file, previous);
      }
      const safe = {};
      for (const [key, value] of Object.entries(fields)) {
        if (/token|key|secret|authorization/iu.test(key)) continue;
        safe[key] = typeof value === "string" ? redact(value) : value;
      }
      fs.appendFileSync(this.file, `${JSON.stringify({
        timestamp: new Date().toISOString(), component, event, ...safe,
      })}\n`, { encoding: "utf8", mode: 0o600 });
    } catch {
      // Runtime logging must never crash the supervisor.
    }
  }
}

function validateConfiguredPython(variable) {
  const configured = String(process.env[variable] || process.env.AKASHI_RUNTIME_PYTHON || "").trim();
  if (!configured) return null;
  if (!path.isAbsolute(configured) || path.extname(configured).toLowerCase() !== ".exe" || !fs.existsSync(configured)) {
    throw new Error(`${variable} must be an existing absolute .exe path.`);
  }
  return path.resolve(configured);
}

function discoverPython(variable) {
  const configured = validateConfiguredPython(variable);
  if (configured) return configured;
  const executable = execFileSync("py", ["-3.11", "-c", "import sys; print(sys.executable)"], {
    encoding: "utf8", windowsHide: true, timeout: 10_000,
  }).trim();
  if (!path.isAbsolute(executable) || !fs.existsSync(executable) || path.extname(executable).toLowerCase() !== ".exe") {
    throw new Error("A valid Python 3.11 runtime was not found.");
  }
  return path.resolve(executable);
}

/**
 * Extra CORS origins for remote presence clients (e.g. "capacitor://localhost" for the
 * AKASHI phone app, or the HTTPS origin serving /remote). Explicit opt-in via
 * AKASHI_REMOTE_ORIGINS; only well-formed origins without paths, never "*".
 */
function remoteOrigins(value) {
  const accepted = [];
  for (const raw of String(value || "").split(",")) {
    const item = raw.trim();
    if (!item) continue;
    let url;
    try { url = new URL(item); } catch { continue; }
    if (!["https:", "capacitor:", "http:"].includes(url.protocol)) continue;
    if (url.protocol === "http:" && !isLoopbackUrl(item)) continue;  // plain HTTP only for loopback development
    if (url.username || url.password || url.search || url.hash || !/^\/?$/u.test(url.pathname)) continue;
    const origin = url.protocol === "capacitor:" ? `capacitor://${url.host}` : url.origin;
    if (!accepted.includes(origin)) accepted.push(origin);
  }
  return accepted.slice(0, 16);
}

function boundedEnvironment(additions) {
  const allowed = [
    "SystemRoot", "WINDIR", "PATH", "PATHEXT", "TEMP", "TMP", "USERPROFILE",
    "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "COMSPEC",
  ];
  const output = {};
  for (const name of allowed) {
    if (process.env[name]) output[name] = process.env[name];
  }
  return { ...output, PYTHONUNBUFFERED: "1", ...additions };
}

async function probeJson(url, token, timeoutMs = 2500) {
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  try {
    const response = await fetch(url, {
      headers, redirect: "error", signal: AbortSignal.timeout(timeoutMs),
    });
    let body = null;
    try { body = await response.json(); } catch { body = null; }
    return { reachable: true, ok: response.ok, status: response.status, body };
  } catch (error) {
    return { reachable: false, ok: false, status: 0, error: error?.name || "network_error" };
  }
}

function initialComponent(detail) {
  return { state: "STARTING", detail, pid: null, owned: false, restartCount: 0 };
}

class DesktopRuntimeSupervisor extends EventEmitter {
  constructor(options) {
    super();
    this.userData = path.resolve(options.userData);
    this.resourcesPath = path.resolve(options.resourcesPath);
    this.appDirectory = path.resolve(options.appDirectory);
    this.isPackaged = Boolean(options.isPackaged);
    this.getConnectionConfig = options.getConnectionConfig;
    this.getProviderEnv = options.getProviderEnv || (() => ({ aiProvider: "", geminiApiKey: "", geminiModel: "" }));
    this.getAgentToken = options.getAgentToken;
    this.stopVoice = options.stopVoice || (() => undefined);
    this.probeVoice = options.probeVoice || (async () => ({ ok: false }));
    this.agentPort = boundedPort(process.env.AKASHI_AGENT_PORT, 8765);
    this.heartbeatMs = Math.max(750, Math.min(Number(process.env.AKASHI_RUNTIME_HEARTBEAT_MS || 3000), 30_000));
    this.startupTimeoutMs = Math.max(3000, Math.min(Number(process.env.AKASHI_RUNTIME_STARTUP_TIMEOUT_MS || 20_000), 60_000));
    this.logger = new RuntimeLogger(path.join(this.userData, "logs"));
    this.children = new Map();
    this.intentionalChildren = new WeakSet();
    this.failureTimes = new Map();
    this.recovering = new Set();
    this.started = false;
    this.stopping = false;
    this.heartbeat = null;
    this.initialization = null;
    this.snapshot = {
      overall: "STARTING",
      coreMode: "remote",
      updatedAt: new Date().toISOString(),
      components: {
        core: initialComponent("Core configuration pending."),
        agent: initialComponent("Windows Agent startup pending."),
        ollama: initialComponent("Dependency check pending."),
        comfyui: initialComponent("Dependency check pending."),
        voice: initialComponent("Voice engine check pending."),
      },
    };
  }

  status() {
    return JSON.parse(JSON.stringify(this.snapshot));
  }

  _set(component, state, detail, extra = {}) {
    if (!STATES.has(state)) throw new Error(`Invalid runtime state: ${state}`);
    this.snapshot.components[component] = {
      ...this.snapshot.components[component], state, detail: redact(detail), ...extra,
    };
    this.snapshot.updatedAt = new Date().toISOString();
    this._deriveOverall();
    this.emit("state", this.status());
  }

  _deriveOverall() {
    const values = this.snapshot.components;
    if ([values.core.state, values.agent.state].includes("FAILED")) this.snapshot.overall = "FAILED";
    else if ([values.core.state, values.agent.state].includes("RECOVERING")) this.snapshot.overall = "RECOVERING";
    else if (values.core.state === "STARTING" || values.agent.state === "STARTING") this.snapshot.overall = "STARTING";
    else if (values.core.state !== "READY") this.snapshot.overall = "OFFLINE";
    else if (Object.values(values).some((item) => item.state !== "READY")) this.snapshot.overall = "DEGRADED";
    else this.snapshot.overall = "READY";
  }

  _roots() {
    if (this.isPackaged) {
      return {
        core: path.join(this.resourcesPath, "core"),
        agent: path.join(this.resourcesPath, "agent"),
      };
    }
    return {
      core: path.resolve(this.appDirectory, "../../backend"),
      agent: path.resolve(this.appDirectory, "../agent"),
    };
  }

  async start() {
    if (this.initialization) return this.initialization;
    this.initialization = this._initialize();
    return this.initialization;
  }

  async _initialize() {
    this.started = true;
    this.stopping = false;
    const config = this.getConnectionConfig();
    this.snapshot.coreMode = config.coreMode;
    this.logger.write("supervisor", "starting", { coreMode: config.coreMode });
    await Promise.allSettled([
      this._ensureAgent(true),
      this._ensureCore(true),
      this._checkExternalDependencies(),
      this._checkVoice(),
    ]);
    if (!this.stopping) {
      this.heartbeat = setInterval(() => { void this._heartbeat(); }, this.heartbeatMs);
      if (typeof this.heartbeat.unref === "function") this.heartbeat.unref();
    }
    this._deriveOverall();
    this.emit("state", this.status());
    return this.status();
  }

  async whenReady() {
    if (!this.initialization) await this.start();
    return this.initialization;
  }

  _spawn(component, executable, args, cwd, env) {
    if (!path.isAbsolute(executable) || !fs.existsSync(executable)) {
      throw new Error(`${component} runtime executable is unavailable.`);
    }
    if (!path.isAbsolute(cwd) || !fs.existsSync(cwd)) {
      throw new Error(`${component} runtime files are unavailable.`);
    }
    const child = spawn(executable, args, {
      cwd, env, shell: false, windowsHide: true, detached: false,
      stdio: ["ignore", "pipe", "pipe"],
    });
    this.children.set(component, child);
    let recentError = "";
    child.stderr.on("data", (chunk) => {
      recentError = (recentError + chunk.toString("utf8")).slice(-500);
    });
    child.stdout.on("data", () => undefined);
    child.once("spawn", () => {
      this.logger.write(component, "spawned", { pid: child.pid });
      this._set(component, "STARTING", `${component} process started.`, { pid: child.pid, owned: true });
    });
    child.once("error", (error) => {
      this.logger.write(component, "spawn_error", { errorCategory: error.code || error.name });
    });
    child.once("exit", (code, signal) => {
      if (this.children.get(component) === child) this.children.delete(component);
      this.logger.write(component, "exited", {
        pid: child.pid, code, signal, errorCategory: recentError ? "process_stderr" : "process_exit",
      });
      if (!this.stopping && this.started && !this.intentionalChildren.has(child)) {
        void this._recover(component, "Owned process exited.");
      }
    });
    return child;
  }

  async _waitFor(probe, timeoutMs = this.startupTimeoutMs) {
    const deadline = Date.now() + timeoutMs;
    while (!this.stopping && Date.now() < deadline) {
      const result = await probe();
      if (result.ok) return result;
      if (result.reachable && result.status === 401) return result;
      await new Promise((resolve) => setTimeout(resolve, 350));
    }
    return { reachable: false, ok: false, status: 0, error: "startup_timeout" };
  }

  async _probeAgent() {
    const token = this.getAgentToken();
    const health = await probeJson(`http://127.0.0.1:${this.agentPort}/health`, null);
    if (!health.ok) return health;
    return probeJson(`http://127.0.0.1:${this.agentPort}/v1/capabilities`, token);
  }

  async _ensureAgent(initial = false) {
    if (this.stopping) return;
    const existing = await this._probeAgent();
    if (existing.ok) {
      const child = this.children.get("agent");
      this._set("agent", "READY", "Windows Agent authenticated.", {
        pid: child?.pid || null, owned: Boolean(child),
      });
      return;
    }
    if (existing.reachable && existing.status === 401) {
      this._set("agent", "FAILED", "A loopback Agent is running with a different credential. Manual attention required.", { pid: null, owned: false });
      return;
    }
    let attemptRecorded = false;
    if (!initial) {
      if (!this._recordFailure("agent")) return;
      attemptRecorded = true;
    }
    try {
      const roots = this._roots();
      const python = discoverPython("AKASHI_AGENT_PYTHON");
      const agentModule = path.join(roots.agent, "akashi_agent", "__init__.py");
      if (!fs.existsSync(agentModule)) throw new Error("Packaged Windows Agent files are missing.");
      const runtimeRoot = path.join(this.userData, "runtime", "agent");
      fs.mkdirSync(runtimeRoot, { recursive: true });
      const inheritedRoots = String(process.env.AKASHI_AGENT_ALLOWED_ROOTS || "").trim();
      const env = boundedEnvironment({
        PYTHONPATH: roots.agent,
        AKASHI_AGENT_TOKEN: this.getAgentToken(),
        AKASHI_AGENT_CAPTURE_DIR: path.join(runtimeRoot, "captures"),
        AKASHI_AGENT_CREDENTIAL_FILE: path.join(runtimeRoot, "device.credential"),
        ...(inheritedRoots ? { AKASHI_AGENT_ALLOWED_ROOTS: inheritedRoots } : {}),
      });
      this._spawn("agent", python, ["-m", "akashi_agent", "serve", "--port", String(this.agentPort)], roots.agent, env);
      const ready = await this._waitFor(() => this._probeAgent());
      if (!ready.ok) throw new Error(ready.status === 401 ? "Agent credential mismatch." : "Agent startup timed out.");
      const child = this.children.get("agent");
      this._set("agent", "READY", "Windows Agent authenticated.", {
        pid: child?.pid || null, owned: true,
      });
    } catch (error) {
      if (!attemptRecorded) this._recordFailure("agent");
      this.logger.write("agent", "startup_failed", { errorCategory: error?.name || "Error", detail: error?.message });
      this._set("agent", this._crashLooped("agent") ? "FAILED" : "OFFLINE", `${error.message} ${this._crashLooped("agent") ? "Manual attention required." : ""}`.trim());
      if (!this.stopping && !this._crashLooped("agent")) {
        setTimeout(() => { void this._recover("agent", "Windows Agent startup failed."); }, 500);
      }
    }
  }

  async _probeCore(config) {
    if (!config.baseUrl) return { reachable: false, ok: false, status: 0, error: "not_configured" };
    const health = await probeJson(`${config.baseUrl}/health`, null);
    if (!health.ok) return health;
    return probeJson(`${config.baseUrl}/auth/check`, config.token);
  }

  async _ensureCore(initial = false) {
    if (this.stopping) return;
    const config = this.getConnectionConfig();
    this.snapshot.coreMode = config.coreMode;
    const existing = await this._probeCore(config);
    if (existing.ok) {
      const child = this.children.get("core");
      this._set("core", "READY", `${config.coreMode === "local" ? "Local" : "Remote"} Core authenticated.`, {
        pid: child?.pid || null, owned: Boolean(child),
      });
      return;
    }
    if (config.coreMode === "remote") {
      const detail = !config.baseUrl ? "Remote Core is not configured." : existing.status === 401 ? "Remote Core rejected the configured credential." : "Remote Core is offline.";
      this._set("core", existing.status === 401 ? "FAILED" : "OFFLINE", detail, { pid: null, owned: false });
      return;
    }
    if (!isLoopbackUrl(config.baseUrl)) {
      this._set("core", "FAILED", "Local Core mode requires a loopback backend URL.", { pid: null, owned: false });
      return;
    }
    if (existing.reachable && existing.status === 401) {
      this._set("core", "FAILED", "A loopback Core is running with a different credential. Manual attention required.", { pid: null, owned: false });
      return;
    }
    let attemptRecorded = false;
    if (!initial) {
      if (!this._recordFailure("core")) return;
      attemptRecorded = true;
    }
    try {
      const roots = this._roots();
      const python = discoverPython("AKASHI_BACKEND_PYTHON");
      if (!fs.existsSync(path.join(roots.core, "app", "main.py"))) throw new Error("Packaged Core files are missing.");
      if (!config.token || config.token.length < 32) throw new Error("Local Core credential is unavailable.");
      const url = new URL(config.baseUrl);
      const corePort = boundedPort(url.port, 8000);
      const inherited = {};
      const allowed = [
        "OLLAMA_BASE_URL", "OLLAMA_MODEL", "OLLAMA_TIMEOUT_SECONDS",
        "COMFY_BASE_URL", "RESEARCH_PROVIDER",
        "WIKIPEDIA_LANGUAGE", "SEARXNG_BASE_URL", "RESEARCH_TIMEOUT_SECONDS",
        "AKASHI_MODEL_FAST_PROVIDER", "AKASHI_MODEL_QUALITY_PROVIDER",
        "AKASHI_MODEL_REASONING_PROVIDER", "AKASHI_MODEL_VISION_PROVIDER",
        "AKASHI_MODEL_FAST_NAME", "AKASHI_MODEL_QUALITY_NAME",
        "AKASHI_MODEL_REASONING_NAME", "AKASHI_MODEL_VISION_NAME",
        "MISS_MINUTES_ENABLED", "MISS_MINUTES_TIMEZONE", "AKASHI_PROJECT_PATH",
        "AKASHI_FORM_DATA_DIR", "AKASHI_SPATIAL_INTERPRETER", "AKASHI_REMOTE_ENDPOINTS",
      ];
      for (const name of allowed) if (process.env[name]) inherited[name] = process.env[name];
      // AI_PROVIDER/GEMINI_API_KEY/GEMINI_MODEL never come from process.env: a packaged app has no
      // backend/.env to read (extraResources never ships it), so they live only in the safeStorage-
      // encrypted provider.secure store and are injected here, decrypted, straight into the child env.
      const providerConfig = this.getProviderEnv() || {};
      if (providerConfig.aiProvider) inherited.AI_PROVIDER = providerConfig.aiProvider;
      if (providerConfig.geminiApiKey) inherited.GEMINI_API_KEY = providerConfig.geminiApiKey;
      if (providerConfig.geminiModel) inherited.GEMINI_MODEL = providerConfig.geminiModel;
      const runtimeRoot = path.join(this.userData, "runtime", "core");
      fs.mkdirSync(runtimeRoot, { recursive: true });
      const env = boundedEnvironment({
        ...inherited,
        PYTHONPATH: roots.core,
        AKASHI_DATA_DIR: runtimeRoot,
        AKASHI_API_TOKEN: config.token,
        AKASHI_AGENT_TOKEN: this.getAgentToken(),
        AKASHI_AGENT_URL: `http://127.0.0.1:${this.agentPort}`,
        AKASHI_CORS_ORIGINS: ["akashi://app", ...remoteOrigins(process.env.AKASHI_REMOTE_ORIGINS)].join(","),
      });
      if (providerConfig.aiProvider) {
        this.logger.write("core", "provider_configured", { provider: providerConfig.aiProvider });
      }
      this._spawn("core", python, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(corePort), "--no-access-log"], roots.core, env);
      const ready = await this._waitFor(() => this._probeCore(config));
      if (!ready.ok) throw new Error(ready.status === 401 ? "Core credential mismatch." : "Core startup timed out.");
      const child = this.children.get("core");
      this._set("core", "READY", "Local Core authenticated.", {
        pid: child?.pid || null, owned: true,
      });
    } catch (error) {
      if (!attemptRecorded) this._recordFailure("core");
      this.logger.write("core", "startup_failed", { errorCategory: error?.name || "Error", detail: error?.message });
      this._set("core", this._crashLooped("core") ? "FAILED" : "OFFLINE", `${error.message} ${this._crashLooped("core") ? "Manual attention required." : ""}`.trim());
      if (!this.stopping && !this._crashLooped("core")) {
        setTimeout(() => { void this._recover("core", "Local Core startup failed."); }, 500);
      }
    }
  }

  _recordFailure(component) {
    const now = Date.now();
    const values = (this.failureTimes.get(component) || []).filter((value) => now - value < RESTART_WINDOW_MS);
    values.push(now);
    this.failureTimes.set(component, values);
    const current = this.snapshot.components[component];
    current.restartCount = values.length;
    if (values.length >= MAX_FAILURES) {
      this._set(component, "FAILED", `${component} entered crash-loop protection. Manual attention required.`, { restartCount: values.length });
      this.logger.write(component, "crash_loop_blocked", { restartCount: values.length });
      return false;
    }
    return true;
  }

  _crashLooped(component) {
    const now = Date.now();
    return (this.failureTimes.get(component) || []).filter((value) => now - value < RESTART_WINDOW_MS).length >= MAX_FAILURES;
  }

  async _terminateOwned(component) {
    const child = this.children.get(component);
    if (!child) return;
    this.children.delete(component);
    if (child.exitCode !== null) return;
    this.intentionalChildren.add(child);
    try { child.kill(); } catch { return; }
    await new Promise((resolve) => {
      const timer = setTimeout(resolve, 2500);
      child.once("exit", () => { clearTimeout(timer); resolve(); });
    });
    if (child.exitCode === null && Number.isInteger(child.pid)) {
      spawnSync("taskkill.exe", ["/PID", String(child.pid), "/T", "/F"], {
        windowsHide: true, shell: false, stdio: "ignore", timeout: 5000,
      });
    }
  }

  async _recover(component, reason) {
    if (this.stopping || this.recovering.has(component) || !["agent", "core"].includes(component)) return;
    if (component === "core" && this.getConnectionConfig().coreMode !== "local") {
      this._set("core", "OFFLINE", "Remote Core is offline.", { pid: null, owned: false });
      return;
    }
    if (this._crashLooped(component)) {
      this._set(component, "FAILED", `${component} entered crash-loop protection. Manual attention required.`);
      return;
    }
    this.recovering.add(component);
    this._set(component, "RECOVERING", reason);
    try {
      await this._terminateOwned(component);
      const failures = (this.failureTimes.get(component) || []).length;
      await new Promise((resolve) => setTimeout(resolve, Math.min(4000, 500 * (2 ** failures))));
      if (component === "agent") await this._ensureAgent(false);
      else await this._ensureCore(false);
    } finally {
      this.recovering.delete(component);
    }
  }

  async _heartbeat() {
    if (this.stopping) return;
    const [agent, core] = await Promise.all([
      this._probeAgent(), this._probeCore(this.getConnectionConfig()),
    ]);
    if (agent.ok && !["READY", "FAILED"].includes(this.snapshot.components.agent.state)) {
      const child = this.children.get("agent");
      this._set("agent", "READY", "Windows Agent re-authenticated.", {
        pid: child?.pid || null, owned: Boolean(child),
      });
    } else if (!agent.ok && this.snapshot.components.agent.state === "READY") {
      void this._recover("agent", "Windows Agent heartbeat lost.");
    }
    if (core.ok && !["READY", "FAILED"].includes(this.snapshot.components.core.state)) {
      const child = this.children.get("core");
      this._set("core", "READY", `${this.snapshot.coreMode === "local" ? "Local" : "Remote"} Core re-authenticated.`, {
        pid: child?.pid || null, owned: Boolean(child),
      });
    } else if (!core.ok && this.snapshot.components.core.state === "READY") {
      void this._recover("core", "Core heartbeat lost.");
    }
    await this._checkExternalDependencies();
  }

  async _checkExternalDependencies() {
    const ollamaUrl = String(process.env.OLLAMA_BASE_URL || "http://127.0.0.1:11434").replace(/\/$/u, "");
    const comfyUrl = String(process.env.COMFY_BASE_URL || "http://127.0.0.1:8188").replace(/\/$/u, "");
    if (!isLoopbackUrl(ollamaUrl) || !isLoopbackUrl(comfyUrl)) {
      this._set("ollama", "FAILED", "Non-loopback Ollama probing is refused by Desktop.", { pid: null, owned: false });
      this._set("comfyui", "FAILED", "Non-loopback ComfyUI probing is refused by Desktop.", { pid: null, owned: false });
      return;
    }
    const [ollama, comfy] = await Promise.all([
      probeJson(`${ollamaUrl}/api/tags`, null), probeJson(`${comfyUrl}/system_stats`, null),
    ]);
    this._set("ollama", ollama.ok ? "READY" : "OFFLINE", ollama.ok ? "Ollama detected." : "Ollama offline.", { pid: null, owned: false });
    this._set("comfyui", comfy.ok ? "READY" : "OFFLINE", comfy.ok ? "ComfyUI detected." : "ComfyUI offline.", { pid: null, owned: false });
  }

  async _checkVoice() {
    try {
      const result = await this.probeVoice();
      this._set("voice", result?.ok ? "READY" : "OFFLINE", result?.ok ? "Local voice engine detected." : "Local voice engine unavailable.", { pid: null, owned: false });
    } catch {
      this._set("voice", "OFFLINE", "Local voice engine unavailable.", { pid: null, owned: false });
    }
  }

  async recover(component) {
    if (!["agent", "core"].includes(component)) throw new Error("Only managed components may be recovered.");
    this.failureTimes.delete(component);
    await this._recover(component, "Manual recovery requested.");
    return this.status();
  }

  async reconfigure() {
    const next = this.getConnectionConfig();
    if (next.coreMode !== this.snapshot.coreMode) {
      await this._terminateOwned("core");
      this.snapshot.coreMode = next.coreMode;
    }
    this.failureTimes.delete("core");
    await this._ensureCore(true);
    return this.status();
  }

  async stop() {
    if (this.stopping) return;
    this.stopping = true;
    this.started = false;
    if (this.heartbeat) clearInterval(this.heartbeat);
    this.heartbeat = null;
    try { await this.stopVoice(); } catch { /* voice cleanup is best-effort */ }
    await Promise.allSettled([
      this._terminateOwned("agent"), this._terminateOwned("core"),
    ]);
    this.logger.write("supervisor", "stopped", {});
  }
}

module.exports = {
  DesktopRuntimeSupervisor,
  RuntimeLogger,
  boundedEnvironment,
  discoverPython,
  isLoopbackUrl,
  probeJson,
  redact,
  remoteOrigins,
};
