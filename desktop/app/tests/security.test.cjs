const { test } = require("node:test");
const assert = require("node:assert/strict");
const { validateSender, validateApiPath, readBoundedBody, validateVoiceOptions } = require("../security.cjs");
test("IPC rejects foreign origins and subframes", () => {
  const frame = { url: "akashi://app/index.html" };
  validateSender({ senderFrame: frame, sender: { mainFrame: frame } });
  assert.throws(() => validateSender({ senderFrame: frame, sender: { mainFrame: {} } }));
  frame.url = "https://evil.example";
  assert.throws(() => validateSender({ senderFrame: frame, sender: { mainFrame: frame } }));
});
test("IPC path cannot escape the configured origin", () => {
  for (const value of ["//evil.example", "/\\evil", "/\n/evil", "https://evil", "/chat#x"]) assert.throws(() => validateApiPath(value));
  assert.equal(validateApiPath("/image/view?filename=x.png"), "/image/view?filename=x.png");
});
test("IPC streaming response is bounded before buffering all bytes", async () => {
  await assert.rejects(readBoundedBody(new Response("123456"), 5));
  assert.equal((await readBoundedBody(new Response("1234"), 5)).toString(), "1234");
});
test("voice IPC accepts only fixed languages and local model profiles", () => {
  assert.deepEqual(validateVoiceOptions({ language: "tr", model: "small" }), { language: "tr", model: "small", bargeIn: false, sessionId: "" });
  assert.deepEqual(validateVoiceOptions({ language: "../../evil", model: "shell.exe" }), { language: "auto", model: "base", bargeIn: false, sessionId: "" });
  assert.equal(validateVoiceOptions({ bargeIn: "true" }).bargeIn, false);
  assert.equal(validateVoiceOptions({ bargeIn: true }).bargeIn, true);
});
test("voice IPC session id is charset-bounded and falls back to worker-generated", () => {
  assert.equal(validateVoiceOptions({ sessionId: "d7f1c2ab-1111-4222-8333-444455556666" }).sessionId, "d7f1c2ab-1111-4222-8333-444455556666");
  for (const value of ["short", "bad id", "has" + String.fromCharCode(10) + "newline", "a".repeat(129), 42, null]) {
    assert.equal(validateVoiceOptions({ sessionId: value }).sessionId, "");
  }
});
