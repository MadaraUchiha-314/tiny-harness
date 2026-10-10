/**
 * Rasterise SVG screenshots (Textual's save_screenshot output) to PNG with Chromium.
 *
 *   TINY_HARNESS_CHROMIUM=/usr/bin/chromium bun run scripts/svg-to-png.ts <file.svg>...
 */
import { chromium } from "@playwright/test";
import { resolve } from "node:path";

const executablePath = process.env["TINY_HARNESS_CHROMIUM"];
const browser = await chromium.launch(executablePath ? { executablePath } : {});
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
for (const file of process.argv.slice(2)) {
  await page.goto(`file://${resolve(file)}`);
  const svg = page.locator("svg").first();
  await svg.screenshot({ path: file.replace(/\.svg$/, ".png") });
}
await browser.close();
