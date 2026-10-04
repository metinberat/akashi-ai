const { test } = require("node:test");
const assert = require("node:assert/strict");
const { validateSender, validateApiPath, readBoundedBody, validateVoiceOptions, allowPermissionRequest, allowPermissionCheck } = require("../security.cjs");
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
test("permissions: only video-only camera from the app main frame is granted", () => {
  const camera = { mediaTypes: ["video"], requestingUrl: "akashi://app/index.html", isMainFrame: true };
  assert.equal(allowPermissionRequest("media", camera), true);
  assert.equal(allowPermissionRequest("media", { ...camera, mediaTypes: ["audio"] }), false);
  assert.equal(allowPermissionRequest("media", { ...camera, mediaTypes: ["video", "audio"] }), false);
  assert.equal(allowPermissionRequest("media", { ...camera, mediaTypes: [] }), false);
  assert.equal(allowPermissionRequest("media", { ...camera, isMainFrame: false }), false);
  assert.equal(allowPermissionRequest("media", { ...camera, requestingUrl: "https://evil.example/" }), false);
  assert.equal(allowPermissionRequest("media", { ...camera, requestingUrl: "akashi://evil/index.html" }), false);
  for (const permission of ["display-capture", "geolocation", "notifications", "clipboard-read", "midi", "openExternal", "fullscreen"]) {
    assert.equal(allowPermissionRequest(permission, camera), false, permission);
  }
  assert.equal(allowPermissionRequest("media", undefined), false);
  assert.equal(allowPermissionCheck("media", "akashi://app", { mediaType: "video" }), true);
  assert.equal(allowPermissionCheck("media", "akashi://app", { mediaType: "audio" }), false);
  assert.equal(allowPermissionCheck("media", "https://evil.example", { mediaType: "video" }), false);
  assert.equal(allowPermissionCheck("geolocation", "akashi://app", { mediaType: "video" }), false);
});
