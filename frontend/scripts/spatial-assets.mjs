// Spatial Lab local-first runtime assets.
//   node scripts/spatial-assets.mjs            copy MediaPipe WASM + fetch the hand model (pinned SHA-256)
//   node scripts/spatial-assets.mjs --offline  copy WASM; verify the model if present; never download
//   node scripts/spatial-assets.mjs --check    verify only; exit 1 if anything is missing or wrong
// The files land in public/spatial/ so the static export (web, Electron) serves
// them from the app origin. Nothing is fetched at runtime.
import { createHash } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const wasmSource = join(root, "node_modules", "@mediapipe", "tasks-vision", "wasm");
const wasmTarget = join(root, "public", "spatial", "mediapipe");
const modelTarget = join(root, "public", "spatial", "models", "hand_landmarker.task");
export const MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";
export const MODEL_SHA256 = "fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1";
const WASM_FILES = ["vision_wasm_internal.js", "vision_wasm_internal.wasm", "vision_wasm_nosimd_internal.js", "vision_wasm_nosimd_internal.wasm"];

const mode = process.argv.includes("--check") ? "check" : process.argv.includes("--offline") ? "offline" : "full";
const sha256 = (buffer) => createHash("sha256").update(buffer).digest("hex");
let problems = 0;

for (const file of WASM_FILES) {
  const source = join(wasmSource, file);
  const target = join(wasmTarget, file);
  if (!existsSync(source)) {
    console.error(`[spatial-assets] missing ${source}; run npm ci`);
    problems += 1;
    continue;
  }
  if (mode === "check") {
    if (!existsSync(target) || sha256(readFileSync(target)) !== sha256(readFileSync(source))) {
      console.error(`[spatial-assets] ${file} is missing or stale in public/spatial/mediapipe`);
      problems += 1;
    }
    continue;
  }
  mkdirSync(wasmTarget, { recursive: true });
  copyFileSync(source, target);
}

if (existsSync(modelTarget)) {
  const digest = sha256(readFileSync(modelTarget));
  if (digest !== MODEL_SHA256) {
    console.error(`[spatial-assets] hand model hash mismatch (${digest}); delete it and re-run without --offline`);
    problems += 1;
  } else {
    console.log("[spatial-assets] hand model present and verified");
  }
} else if (mode === "full") {
  console.log(`[spatial-assets] downloading ${MODEL_URL}`);
  const response = await fetch(MODEL_URL);
  if (!response.ok) throw new Error(`model download failed: HTTP ${response.status}`);
  const buffer = Buffer.from(await response.arrayBuffer());
  const digest = sha256(buffer);
  if (digest !== MODEL_SHA256) throw new Error(`model hash mismatch: ${digest} (expected ${MODEL_SHA256}); refusing to install`);
  mkdirSync(dirname(modelTarget), { recursive: true });
  writeFileSync(modelTarget + ".tmp", buffer);
  renameSync(modelTarget + ".tmp", modelTarget);
  console.log(`[spatial-assets] hand model installed (${buffer.length} bytes, sha256 verified)`);
} else {
  const message = "[spatial-assets] hand model not installed; camera hand tracking will report model_missing. Run `npm run spatial:assets`.";
  if (mode === "check") { console.error(message); problems += 1; } else console.warn(message);
}

if (problems) process.exit(1);
