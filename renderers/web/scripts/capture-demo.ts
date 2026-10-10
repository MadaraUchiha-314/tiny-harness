/**
 * Capture the demo flow in the web renderer against a running demo server (evidence T4/T5).
 *
 *   TINY_HARNESS_CHROMIUM=/usr/bin/chromium bun run scripts/capture-demo.ts <out-dir> [base-url]
 *
 * Writes web-<state>.png at each verified state and frames/frame-NNN.png every 1.5 s for the
 * animated capture. The flow: send the complaint, press the card's Confirm button on the first
 * INPUT_REQUIRED, answer the next question in text, wait for COMPLETED.
 */
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const COMPLAINT =
  "Refund order #48213: the customer says the blender arrived cracked. Check the order and propose a resolution.";
const REPLY =
  "Ship a replacement for order #48213 to the address on the order, 14 Harbour Lane, Portsea. " +
  "The customer reported the crack on 2026-10-06, the day it was delivered, and the other open order #48377 is unrelated. Go ahead.";

const out = process.argv[2] ?? "capture";
const base = process.argv[3] ?? "http://127.0.0.1:8080";
const frames = join(out, "frames");
mkdirSync(frames, { recursive: true });

const executablePath = process.env["TINY_HARNESS_CHROMIUM"];
const browser = await chromium.launch(executablePath ? { executablePath } : {});
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
await page.goto(`${base}/ui/?participant=alice`);

const seen = new Set<string>();
let frame = 0;
let replies = 0;
const started = Date.now();

async function snap(name: string): Promise<void> {
  await page.screenshot({ path: join(out, `web-${name}.png`) });
}

async function state(): Promise<string> {
  const text = (await page.getByTestId("state").textContent()) ?? "";
  return text.trim().toUpperCase().replace(/[\s-]+/g, "_");
}

const composer = page.getByPlaceholder("Message the task…");
await snap("empty");
await composer.fill(COMPLAINT);
await composer.press("Enter");

while (Date.now() - started < 300_000) {
  await page.waitForTimeout(1500);
  await page.screenshot({ path: join(frames, `frame-${String(frame++).padStart(3, "0")}.png`) });
  const current = await state();
  const card = page.getByTestId("a2ui");
  if (current.includes("WORKING") && !seen.has("working")) {
    seen.add("working");
    await snap("working");
  }
  if ((await card.count()) > 0 && !seen.has("card")) {
    seen.add("card");
    await snap("card");
  }
  if (current.includes("INPUT")) {
    if (!seen.has("input-required")) {
      seen.add("input-required");
      await snap("input-required");
    }
    if (replies === 0 && (await card.count()) > 0) {
      const confirm = card.getByRole("button").first();
      if ((await confirm.count()) > 0) {
        replies += 1;
        await confirm.click();
        await page.waitForTimeout(500);
        await snap("action-sent");
        continue;
      }
    }
    if (replies < 4 && (await composer.isEnabled())) {
      replies += 1;
      await composer.fill(REPLY);
      await composer.press("Enter");
      await page.waitForTimeout(500);
      await snap(`reply-${replies}`);
    }
  }
  if (current.includes("COMPLETED") || current.includes("FAILED") || current.includes("CANCELED")) {
    await snap("completed");
    break;
  }
}
console.log(`captured ${frame} frames, states: ${[...seen].join(", ")}, replies: ${replies}`);
await browser.close();
