"use strict";

function validateSender(event) {
  const frame = event.senderFrame;
  if (!frame || frame !== event.sender.mainFrame) throw new Error("Subframe IPC is forbidden.");
  const url = new URL(frame.url);
  if (url.protocol !== "akashi:" || url.hostname !== "app" || url.username || url.password) {
    throw new Error("Untrusted IPC sender.");
  }
}

function validateApiPath(value) {
  if (typeof value !== "string" || value.length > 8192 || !value.startsWith("/") || value.startsWith("//") || /[\\\r\n\t#]/u.test(value)) {
    throw new Error("Invalid backend API path.");
  }
  const url = new URL(value, "https://backend.invalid");
  if (url.origin !== "https://backend.invalid") throw new Error("Invalid backend API path.");
  return value;
}

async function readBoundedBody(response, limit = 60 * 1024 * 1024) {
  if (Number(response.headers.get("content-length")) > limit) {
    await response.body?.cancel();
    throw new Error("Backend response exceeds the desktop safety limit.");
  }
  if (!response.body) return Buffer.alloc(0);
  const reader = response.body.getReader();
  const chunks = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > limit) { await reader.cancel(); throw new Error("Backend response exceeds the desktop safety limit."); }
      chunks.push(Buffer.from(value));
    }
  } finally { reader.releaseLock(); }
  return Buffer.concat(chunks, total);
}

function validateVoiceOptions(value) {
  const language = ["auto", "tr", "en"].includes(value?.language) ? value.language : "auto";
  const model = ["tiny", "base", "small"].includes(value?.model) ? value.model : "base";
  const bargeIn = value?.bargeIn === true;
  // Renderer-supplied conversation id, so a voice turn that consults Core lands
  // in the same conversation as the typed chat. An unusable value degrades to
  // "", which makes the worker fall back to its own generated id.
  const sessionId = typeof value?.sessionId === "string" && /^[A-Za-z0-9._:-]{8,128}$/u.test(value.sessionId)
    ? value.sessionId
    : "";
  return { language, model, bargeIn, sessionId };
}

module.exports = { validateSender, validateApiPath, readBoundedBody, validateVoiceOptions };
