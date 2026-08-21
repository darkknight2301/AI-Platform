import { defineConfig, devices } from "@playwright/test";

/**
 * Phase 11 E2E config. Assumes the backend (localhost:8000, backed by
 * a real Postgres — see backend/.env.example) and frontend dev server
 * (localhost:5173) are already running, OR lets Playwright start the
 * frontend dev server itself via `webServer` below (it does NOT start
 * the backend/DB — those have external dependencies this config can't
 * own). See frontend/tests/e2e/README.md for the full setup.
 */
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false, // tests share backend state (users, audit log counts); keep sequential per file
  retries: process.env.CI ? 1 : 0,
  reporter: [["html", { open: "never" }], ["list"]],
  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
