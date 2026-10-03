const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { localRequest, environment } = require("../desktop/security.cjs");
test("token can only attach to exact local product API origin", () => {
  const origin = "http://127.0.0.1:5000";
  assert(localRequest(origin + "/api/projects", origin));
  for (const url of [
    "http://127.0.0.1:5001/api/",
    "https://evil.test/api/",
    "http://127.0.0.1:5000.evil.test/api/",
    origin + "/style.css",
  ])
    assert.equal(localRequest(url, origin), false);
});
test("bounded child environment and no secret on command line", () => {
  const env = environment(
    {
      PATH: "safe",
      AWS_SECRET_ACCESS_KEY: "not inherited",
      AKASHI_API_TOKEN: "not inherited",
      FORM_GEMINI_API_KEY: "explicit",
    },
    ["engine"],
    "data",
    "web",
    "temporary",
  );
  assert.equal(env.AWS_SECRET_ACCESS_KEY, undefined);
  assert.equal(env.AKASHI_API_TOKEN, undefined);
  assert.equal(env.FORM_GEMINI_API_KEY, "explicit");
  assert.equal(env.FORM_RUNTIME_TOKEN, "temporary");
  const src = fs.readFileSync(
    path.join(__dirname, "../desktop/main.cjs"),
    "utf8",
  );
  assert(/\["-m",\s*"form_studio\.runtime"\]/.test(src));
});
test("desktop boundary remains sandboxed without renderer Node or arbitrary IPC", () => {
  const src = fs.readFileSync(
    path.join(__dirname, "../desktop/main.cjs"),
    "utf8",
  );
  assert(src.includes("sandbox: true"));
  assert(src.includes("contextIsolation: true"));
  assert(src.includes("nodeIntegration: false"));
  assert(src.includes("shell: false"));
  assert(src.includes("requestSingleInstanceLock"));
  assert(!src.includes("ipcMain.handle"));
  assert(!src.includes("webSecurity: false"));
});
