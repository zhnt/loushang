import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/browser",
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45_000,
  outputDir: "test-results/layout",
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:1421",
    browserName: "chromium",
    channel: "chromium",
    headless: true,
    reducedMotion: "reduce",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "pnpm exec vite --host 127.0.0.1 --port 1421 --strictPort",
    url: "http://127.0.0.1:1421",
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
