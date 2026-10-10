import { defineConfig } from "@playwright/test";

const executablePath = process.env["TINY_HARNESS_CHROMIUM"];

export default defineConfig({
  testDir: "e2e",
  snapshotPathTemplate: "e2e/__snapshots__/{testFilePath}/{arg}{ext}",
  use: {
    baseURL: "http://127.0.0.1:4173",
    ...(executablePath ? { launchOptions: { executablePath } } : {}),
  },
  webServer: {
    command: "bun x vite preview --host 127.0.0.1 --port 4173 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: true,
  },
  projects: [
    { name: "visual", testMatch: /visual\.spec\.ts/ },
    { name: "a11y", testMatch: /a11y\.spec\.ts/ },
  ],
});
