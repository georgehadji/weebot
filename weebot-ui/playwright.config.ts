import { defineConfig, devices } from "@playwright/test";

// Default: a production build (deterministic, no on-demand compiling mid-test), served on its own
// port from its own build directory. E2E_DEV=1 reuses `npm run dev` for quick local runs.
const dev = !!process.env.E2E_DEV;
const port = dev ? 3000 : 3100;
const host = dev ? "localhost" : "127.0.0.1";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "line",
  use: {
    baseURL: `http://${host}:${port}`,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: dev
      ? "npm run dev"
      : "node e2e/serve.mjs",
    url: `http://${host}:${port}`,
    reuseExistingServer: !process.env.CI,
    timeout: 240_000,
  },
});
