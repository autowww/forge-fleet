import { defineConfig } from "@playwright/test";

const PORT = 19876;
const BASE = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "e2e",
  workers: 1,
  timeout: 180_000,
  expect: { timeout: 45_000 },
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: BASE,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "bash ./e2e/start-fleet-server.sh",
    url: `${BASE}/v1/health`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
