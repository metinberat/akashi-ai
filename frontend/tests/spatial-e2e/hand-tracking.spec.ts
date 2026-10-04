// Real hand-tracking path in a real browser: Chromium fake camera device fed
// with MediaPipe's own hand photographs → getUserMedia → MediaPipe Hand
// Landmarker (local WASM + pinned model) → Spatial Lab live provider →
// product recorder. The recorded REAL landmarks then run through the gesture
// pipeline. Scope: still photos, cloud CPU, no live motion — this is NOT a
// physical webcam acceptance (docs/acceptance/spatial-lab-v1.md).
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

import { chromium, expect, test } from "@playwright/test";

import { gestureConfig } from "../../src/lib/spatial/gesture/config.ts";
import { computeFeatures } from "../../src/lib/spatial/gesture/hand.ts";
import { GesturePipeline } from "../../src/lib/spatial/gesture/pipeline.ts";
import { DEFAULT_RIG, PerspectiveProjector } from "../../src/lib/spatial/projection.ts";
import { recordingFrames, validateRecording, type HandRecording } from "../../src/lib/spatial/providers/recorded.ts";

const CORE = "http://127.0.0.1:8017";
const TOKEN = "spatial-e2e-token-0000000000000000000000";
const CAMERA_DIR = path.resolve("tests/spatial-e2e/.artifacts/camera");
const REPORT_DIR = path.resolve("tests/spatial-e2e/.artifacts/hand-tracking");

type Expectation = { hands: number; pose: "grab" | "none" | "report" };
const PHOTOS: Record<string, Expectation> = {
  fist: { hands: 1, pose: "grab" },
  victory: { hands: 1, pose: "none" },
  pointing_up: { hands: 1, pose: "none" }, // regression: mean-extension grab misfired on this real photo
  thumb_up: { hands: 1, pose: "report" },
  right_hands: { hands: 2, pose: "none" },
  left_hands: { hands: 2, pose: "none" },
};

const median = (values: number[]) => {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted.length ? sorted[Math.floor(sorted.length / 2)] : Number.NaN;
};

const RUNS = [...Object.entries(PHOTOS).map(([photo, expected]) => ({ photo, expected, delegate: "GPU" as const })),
  { photo: "fist", expected: PHOTOS.fist, delegate: "CPU" as const }];

for (const { photo, expected, delegate } of RUNS) {
  test(`live provider on real photo: ${photo} (${delegate} delegate)`, async () => {
    test.setTimeout(150_000);
    // Each photo needs its own fake camera file, which is a browser launch flag.
    const browser = await chromium.launch({
      executablePath: process.env.CHROMIUM_PATH || undefined,
      args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", `--use-file-for-fake-video-capture=${path.join(CAMERA_DIR, `${photo}.y4m`)}`],
    });
    try {
      const page = await (await browser.newContext({ baseURL: "http://localhost:3101", viewport: { width: 1440, height: 900 }, acceptDownloads: true })).newPage();
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.addInitScript(({ token, inference }) => {
        localStorage.setItem("akashi_backend_url", "https://core.spatial.test");
        sessionStorage.setItem("akashi_backend_token", token);
        localStorage.setItem("akashi-spatial-delegate", JSON.stringify({ value: inference }));
      }, { token: TOKEN, inference: delegate });
      await page.route("https://core.spatial.test/**", async (route) => {
        await route.fulfill({ response: await route.fetch({ url: route.request().url().replace("https://core.spatial.test", CORE) }) });
      });
      await page.goto("/");
      await page.getByRole("navigation", { name: "Ana menü" }).getByRole("button", { name: /More/ }).click();
      await page.getByRole("button", { name: /Spatial Lab/ }).click();
      await page.getByRole("button", { name: "Camera", exact: true }).click();
      const state = page.locator(".spatial-input-state");
      await expect(state).toHaveAttribute("data-state", "running", { timeout: 120_000 });
      await expect(page.locator(".spatial-stage")).toHaveAttribute("data-camera", "true");
      await page.getByRole("button", { name: "Debug" }).click();
      await page.getByRole("button", { name: "Record hands" }).click();
      // Record a fixed number of frames, not a fixed wall time: the first GPU
      // run in a fresh browser pays shader warm-up on software GL.
      const counter = page.locator("[data-recorded-frames]");
      await expect.poll(async () => Number(await counter.getAttribute("data-recorded-frames")), { timeout: 60_000 }).toBeGreaterThanOrEqual(12);
      const debugText = await page.getByRole("region", { name: "Spatial debug" }).innerText();
      const download = page.waitForEvent("download");
      await page.getByRole("button", { name: "Stop & save recording" }).click();
      const file = await (await download).path();
      const recording = validateRecording(JSON.parse(readFileSync(file, "utf8"))) as HandRecording;

      // Real landmarks → features (aspect from the real camera frames).
      const aspect = recording.source.resolution.width / recording.source.resolution.height;
      const perFrame = recording.frames.map((frame) => frame.hands.length);
      const features = recording.frames.flatMap((frame) => frame.hands.map((hand) => ({ handedness: hand.handedness, score: hand.handednessScore, ...computeFeatures(hand, aspect, (p) => p) })));
      // Real landmarks → the same deterministic pipeline used in production.
      const pipeline = new GesturePipeline(gestureConfig(), new PerspectiveProjector(DEFAULT_RIG, aspect), () => false, () => 0);
      const scene = { objects: [], selection: [], limits: { position_min: [-4, -1, -4] as [number, number, number], position_max: [4, 4, 2] as [number, number, number], scale_min: 0.1, scale_max: 10 } };
      let everPinch = false;
      let everGrab = false;
      for (const frame of recordingFrames(recording)) {
        const out = pipeline.process(frame, scene, (p) => p);
        everPinch ||= out.poses.some((p) => p.pinch);
        everGrab ||= out.poses.some((p) => p.grab);
      }
      const report = {
        photo,
        scope: "Chromium fake camera with a still MediaPipe test photograph on cloud CPU; not a physical webcam result.",
        frames: recording.frames.length,
        resolution: recording.source.resolution,
        device: recording.source.device ?? null,
        delegate: recording.source.delegate ?? null,
        frames_with_expected_hands: perFrame.filter((n) => n === expected.hands).length,
        max_hands: Math.max(...perFrame),
        handedness_labels: [...new Set(features.map((f) => f.handedness))],
        median_score: median(features.map((f) => f.score)),
        median_pinch_ratio: median(features.map((f) => f.pinchRatio)),
        median_extension: median(features.map((f) => f.extension)),
        median_index_extension: median(features.map((f) => f.indexExtension)),
        median_inference_ms: median(recording.frames.map((f) => f.inferenceMs ?? Number.NaN).filter(Number.isFinite)),
        pipeline: { ever_pinch: everPinch, ever_grab: everGrab },
        debug_panel: debugText.replace(/\s+/gu, " ").slice(0, 600),
      };
      mkdirSync(REPORT_DIR, { recursive: true });
      const stem = delegate === "GPU" ? photo : `${photo}.${delegate.toLowerCase()}`;
      writeFileSync(path.join(REPORT_DIR, `${stem}.json`), JSON.stringify(report, null, 2));
      writeFileSync(path.join(REPORT_DIR, `${stem}.recording.json`), JSON.stringify(recording));

      expect(recording.source.kind).toBe("live");
      expect(recording.source.delegate).toContain(delegate);
      expect(recording.frames.length).toBeGreaterThanOrEqual(8);
      expect(report.frames_with_expected_hands / recording.frames.length).toBeGreaterThanOrEqual(0.8);
      expect(everPinch).toBe(false); // none of these photos shows a pinch
      if (expected.pose === "grab") expect(everGrab).toBe(true);
      if (expected.pose === "none") expect(everGrab).toBe(false);
      expect(errors).toEqual([]);
    } finally {
      for (const context of browser.contexts()) for (const page of context.pages()) await page.unrouteAll({ behavior: "ignoreErrors" });
      await browser.close();
    }
  });
}
