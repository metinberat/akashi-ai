const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const {
  DesktopRuntimeSupervisor,
  RuntimeLogger,
  boundedEnvironment,
  isLoopbackUrl,
  redact,
  remoteOrigins,
} = require("../runtime-supervisor.cjs");

test("runtime URL policy accepts loopback only", () => {
  assert.equal(isLoopbackUrl("http://127.0.0.1:8000"), true);
  assert.equal(isLoopbackUrl("http://localhost:8000"), true);
  assert.equal(isLoopbackUrl("http://192.168.1.10:8000"), false);
  assert.equal(isLoopbackUrl("https://api.example.test"), false);
});

test("bounded child environment does not inherit credentials", () => {
  const old = process.env.GEMINI_API_KEY;
  process.env.GEMINI_API_KEY = "must-not-be-inherited-automatically";
  try {
    const env = boundedEnvironment({ AKASHI_API_TOKEN: "explicit-runtime-token" });
    assert.equal(env.GEMINI_API_KEY, undefined);
    assert.equal(env.AKASHI_API_TOKEN, "explicit-runtime-token");
  } finally {
    if (old === undefined) delete process.env.GEMINI_API_KEY;
    else process.env.GEMINI_API_KEY = old;
  }
});

test("runtime logs redact credentials and omit secret-named fields", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "akashi-runtime-log-"));
  try {
    const logger = new RuntimeLogger(directory);
    logger.write("core", "failed", {
      detail: "Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789",
      apiToken: "never-write-this",
      errorCategory: "auth",
    });
    const value = fs.readFileSync(path.join(directory, "runtime.jsonl"), "utf8");
    assert.equal(value.includes("never-write-this"), false);
    assert.equal(value.includes("abcdefghijklmnopqrstuvwxyz0123456789"), false);
    assert.match(value, /REDACTED/u);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
  assert.match(redact("token=abcdefghijklmnopqrstuvwxyz0123456789"), /REDACTED/u);
});

test("crash-loop protection becomes terminal after bounded failures", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "akashi-runtime-state-"));
  try {
    const supervisor = new DesktopRuntimeSupervisor({
      userData: directory,
      resourcesPath: directory,
      appDirectory: directory,
      isPackaged: false,
      getConnectionConfig: () => ({ coreMode: "remote", baseUrl: "", token: "" }),
      getAgentToken: () => "x".repeat(40),
    });
    assert.equal(supervisor._recordFailure("agent"), true);
    assert.equal(supervisor._recordFailure("agent"), true);
    assert.equal(supervisor._recordFailure("agent"), false);
    assert.equal(supervisor.status().components.agent.state, "FAILED");
    assert.equal(supervisor.status().components.agent.restartCount, 3);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("remote presence origins are explicit, well-formed and never wildcards", () => {
  assert.deepEqual(remoteOrigins(""), []);
  assert.deepEqual(remoteOrigins("capacitor://localhost, https://akashi.lan:8443, https://akashi.lan:8443/"), ["capacitor://localhost", "https://akashi.lan:8443"]);
  assert.deepEqual(remoteOrigins("*,https://evil.example/path,http://192.168.1.4:3100,https://user:pw@x.example,javascript:alert(1)"), []);
  assert.deepEqual(remoteOrigins("http://localhost:3100"), ["http://localhost:3100"]);
});
