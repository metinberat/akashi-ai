import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

// Prepares the integration suite: verifies local MediaPipe assets and builds the
// fake-camera clips from pinned MediaPipe test photographs.
export default function globalSetup() {
  const python = process.env.SPATIAL_E2E_PYTHON || path.resolve(process.platform === "win32" ? "../backend/.venv/Scripts/python.exe" : "../backend/.venv/bin/python");
  execFileSync(process.execPath, ["scripts/spatial-assets.mjs", "--check"], { stdio: "inherit" });
  if (!existsSync(path.join("out", "spatial", "models", "hand_landmarker.task"))) {
    throw new Error("out/ lacks the hand model: run `npm run spatial:assets && npm run build` first.");
  }
  execFileSync(python, ["tests/spatial-e2e/fake_camera.py", "tests/spatial-e2e/.artifacts/camera"], { stdio: "inherit" });
}
