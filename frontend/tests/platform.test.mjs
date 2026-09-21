import test from "node:test";
import assert from "node:assert/strict";

import {
  automaticMood,
  canPresentWorkspace,
  presentationForClient,
} from "../src/lib/platform.ts";

test("client presentation separates public, mobile, and desktop powers", () => {
  assert.deepEqual(
    presentationForClient("mobile").primaryNavigation,
    ["home", "chat", "create", "memory", "more"],
  );
  assert.equal(canPresentWorkspace("web", "devices"), false);
  assert.equal(canPresentWorkspace("mobile", "devices"), true);
  assert.equal(presentationForClient("mobile").desktopBody, "secondary");
  assert.equal(presentationForClient("desktop").desktopBody, "primary");
  assert.equal(canPresentWorkspace("desktop", "tasks"), true);
});

test("mood selection is evidence-based and restrained", () => {
  assert.equal(automaticMood({ connected: false, busy: false, intensive: false }), "calm");
  assert.equal(automaticMood({ connected: true, busy: false, intensive: false }), "best");
  assert.equal(automaticMood({ connected: true, busy: true, intensive: true }), "hardcarry");
});
