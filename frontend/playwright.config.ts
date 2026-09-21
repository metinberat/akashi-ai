import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/browser", timeout: 30000, workers: 2,
  use: { baseURL: "http://localhost:3100", headless: true, trace: "retain-on-failure" },
  webServer: { command: "npx serve out -l 3100", url: "http://localhost:3100", reuseExistingServer: false },
});
