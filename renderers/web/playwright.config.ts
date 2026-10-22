import { defineConfig } from "@playwright/test";

const executablePath = process.env["TINY_HARNESS_CHROMIUM"];
// Issue-38: a fake microphone (a beep) granted without a prompt, so the mic records in a
// headless browser; audio may start without a gesture (the tests click anyway).
const args = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required"];

export default defineConfig({
  testDir: "e2e",
  snapshotPathTemplate: "e2e/__snapshots__/{testFilePath}/{arg}{ext}",
  use: {
    baseURL: "http://127.0.0.1:4173",
    launchOptions: { args, ...(executablePath ? { executablePath } : {}) },
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
