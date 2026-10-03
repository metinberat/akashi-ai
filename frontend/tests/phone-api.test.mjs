import assert from "node:assert/strict";
import { test } from "node:test";

process.env.NODE_ENV = "production";
const { getPhoneCalls, getPhoneStatus, hangUpPhoneCall } = await import("../src/lib/phone-api.ts");
const config = { baseUrl: "https://api.example.com", token: "phone-test-token" };

test("phone client uses authenticated Core routes and never contacts SIP directly", async () => {
  const originalFetch = globalThis.fetch;
  const seen = [];
  globalThis.fetch = async (url, init) => {
    seen.push({ url, init });
    if (url.endsWith("/phone/status")) return Response.json({ enabled: true, configured: true });
    if (url.includes("/hangup")) return Response.json({ id: "call-1", state: "ended" });
    return Response.json({ calls: [] });
  };
  try {
    await getPhoneStatus(config);
    await getPhoneCalls(config);
    await hangUpPhoneCall(config, "call-1");
    assert.deepEqual(seen.map((item) => item.url), [
      "https://api.example.com/phone/status",
      "https://api.example.com/phone/calls?limit=12",
      "https://api.example.com/phone/calls/call-1/hangup",
    ]);
    for (const item of seen) {
      assert.equal(new Headers(item.init.headers).get("Authorization"), "Bearer phone-test-token");
    }
    assert.equal(seen[2].init.method, "POST");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
