import path from "node:path";

import { defineConfig } from "@playwright/test";

// Spatial Lab integration suite: the real static UI against a real AKASHI Core
// (FastAPI) started by tests/spatial-e2e/backend.py, plus real MediaPipe hand
// tracking on pinned photographs through Chromium's fake camera. Requires the
// backend virtualenv (SPATIAL_E2E_PYTHON overrides), `npm run spatial:assets`
// and `npm run build`. Network is needed once to fetch the pinned photos.
// CHROMIUM_PATH can point at a preinstalled Chromium when Playwright's own
// browser revision is unavailable.
// Absolute and quoted: cmd.exe cannot run an unquoted "../x/y.exe" path.
const python = process.env.SPATIAL_E2E_PYTHON || path.resolve(process.platform === "win32" ? "../backend/.venv/Scripts/python.exe" : "../backend/.venv/bin/python");

export default defineConfig({
  testDir: "./tests/spatial-e2e",
  globalSetup: "./tests/spatial-e2e/global-setup.ts",
  timeout: 90_000,
  workers: 1,
  outputDir: "./tests/spatial-e2e/.artifacts/results",
  use: {
    baseURL: "http://localhost:3101",
    headless: true,
    trace: "retain-on-failure",
    launchOptions: process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
  },
  webServer: [
    { command: "npx serve out -l 3101", url: "http://localhost:3101", reuseExistingServer: false },
    { command: `"${python}" tests/spatial-e2e/backend.py`, url: "http://127.0.0.1:8017/health", reuseExistingServer: false, timeout: 60_000 },
  ],
});
