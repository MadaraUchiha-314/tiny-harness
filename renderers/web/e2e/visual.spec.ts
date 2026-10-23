import { expect, test, type Page } from "@playwright/test";

/**
 * The prototype's states render in a real browser (T5). Pixel comparison against the
 * baselines under e2e/__snapshots__ is strict only where the baselines were made
 * (TINY_HARNESS_VISUAL_STRICT=1): fonts and the Chromium build differ between machines,
 * so CI asserts the elements and keeps the screenshots as evidence artifacts instead.
 */
const strict = process.env["TINY_HARNESS_VISUAL_STRICT"] === "1";

async function capture(page: Page, name: string, fullPage: boolean): Promise<void> {
  if (strict) {
    await expect(page).toHaveScreenshot(`${name}.png`, { fullPage, maxDiffPixelRatio: 0.02 });
  } else {
    await page.screenshot({ path: `test-results/screens/${name}.png`, fullPage });
  }
}

const states = [
  { name: "light", theme: "light", width: 1280 },
  { name: "dark", theme: "dark", width: 1280 },
  { name: "phone", theme: "light", width: 400 },
];

for (const state of states) {
  test(`prototype state renders (${state.name})`, async ({ page }) => {
    await page.setViewportSize({ width: state.width, height: 900 });
    await page.emulateMedia({ colorScheme: state.theme === "dark" ? "dark" : "light" });
    await page.goto("/?fixture=prototype");
    await expect(page.getByTestId("state")).toHaveText("INPUT_REQUIRED");
    await expect(page.getByTestId("a2ui")).toBeVisible();
    await expect(page.getByTestId("a2ui")).toContainText("Proposed resolution");
    await expect(page.getByTestId("help")).toBeVisible();
    await expect(page.getByTestId("placeholder")).toContainText("application/vnd.example.calendar+json");
    await expect(page.getByTestId("sub-state")).toHaveText("awaiting answer");
    await expect(page.getByRole("button", { name: "Complete" })).toBeEnabled();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    expect(overflow, "no horizontal scroll").toBe(false);
    await capture(page, state.name, true);
  });
}

test("the plan tab shows the DAG", async ({ page }) => {
  await page.goto("/?fixture=prototype");
  await page.getByRole("tab", { name: "Plan" }).click();
  await expect(page.getByRole("tabpanel", { name: "Plan" })).toContainText("Agree resolution with customer");
  await capture(page, "plan", false);
});

/** The task-controls prototype (issue-25, `design/web-task-controls.html`), T5/T6. */
async function openControls(page: Page, theme: string, width: number): Promise<void> {
  await page.setViewportSize({ width, height: 900 });
  await page.emulateMedia({ colorScheme: theme === "dark" ? "dark" : "light" });
  await page.goto("/?fixture=controls");
  await expect(page.getByTestId("state")).toHaveText("INPUT_REQUIRED");
  await expect(page.getByTestId("sub-state")).toHaveText("awaiting next message");
}

async function noOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow, "no horizontal scroll").toBe(false);
}

for (const state of states) {
  test(`task controls render (${state.name})`, async ({ page }) => {
    await openControls(page, state.theme, state.width);
    const controls = page.getByRole("group", { name: "Task controls" });
    await expect(controls.getByRole("button", { name: "Complete" })).toBeEnabled();
    await expect(controls.getByRole("button", { name: "Cancel task" })).toBeEnabled();
    await expect(page.getByRole("tabpanel", { name: "Task" })).toContainText("Summarise the open support tickets");
    await noOverflow(page);
    await capture(page, `controls-${state.name}`, true);
  });
}

test("typing / opens the command listbox", async ({ page }) => {
  await openControls(page, "light", 1280);
  const box = page.getByRole("combobox", { name: "Message or /command" });
  await box.fill("/");
  const listbox = page.getByRole("listbox", { name: "Commands" });
  await expect(listbox).toBeVisible();
  await expect(listbox.getByRole("option")).toHaveCount(4);
  await page.keyboard.press("ArrowDown");
  await expect(box).toHaveAttribute("aria-activedescendant", "cmd-effort");
  await capture(page, "listbox", false);
});

test("a sub-task opens in place and links back to its parent", async ({ page }) => {
  await openControls(page, "light", 1280);
  await page.getByRole("combobox", { name: "Message or /command" }).fill("/sub-task Draft the reply to #48213");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByTestId("command")).toContainText("Created sub-task");
  const link = page.getByRole("tabpanel", { name: "Task" }).getByRole("link");
  await expect(link).toHaveCount(1);
  await capture(page, "sub-task-created", false);
  await link.click();
  await expect(page.getByTestId("parent")).toBeVisible();
  await expect(page.getByRole("tabpanel", { name: "Task" })).toContainText("Draft the reply to #48213");
  expect(new URL(page.url()).searchParams.get("task")).toMatch(/^5b1d/);
  await capture(page, "sub-task-open", false);
  await page.getByTestId("parent").click();
  await expect(page.getByTestId("parent")).toHaveCount(0);
  await expect(page.getByRole("tabpanel", { name: "Task" })).toContainText("Summarise the open support tickets");
});

for (const state of states) {
  test(`complete leaves the task COMPLETED with both controls disabled (${state.name})`, async ({ page }) => {
    await openControls(page, state.theme, state.width);
    await page.getByRole("button", { name: "Complete" }).click();
    await expect(page.getByTestId("state")).toHaveText("COMPLETED");
    await expect(page.getByTestId("sub-state")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Complete" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Cancel task" })).toBeDisabled();
    await expect(page.getByText("completed by you")).toBeVisible();
    await noOverflow(page);
    await capture(page, `completed-${state.name}`, true);
  });
}

/** The multimodal prototype (issue-38, `design/web-multimodal.html`), T5. */
const TINY_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAABAAAAAMCAIAAADkharWAAAAHUlEQVR4nGO8c+cOAymAiSTVoxpGNYxqGNVATQ0A3NQCZlxZHasAAAAASUVORK5CYII=",
  "base64",
);

async function openMedia(page: Page, theme: string, width: number, query = ""): Promise<void> {
  await page.setViewportSize({ width, height: 900 });
  await page.emulateMedia({ colorScheme: theme === "dark" ? "dark" : "light" });
  await page.goto(`/?fixture=media${query}`);
  await expect(page.getByTestId("state")).toHaveText("INPUT_REQUIRED");
  // Images load lazily, when they come near the viewport (critic 6). Whether one far
  // above the bottom loaded before the stream auto-scrolled depends on timing, so bring
  // each into view as a reader scrolling up would, then return to the bottom.
  for (const name of ["Image living-room.png", "Generated: the same room with a green sofa and a rust rug"]) {
    await page.getByTestId("media-image").first().waitFor();
    await scrollUntilLoaded(page, page.getByRole("img", { name }));
  }
  const viewport = page.locator('[data-slot="message-scroller-viewport"]');
  await viewport.evaluate((el) => el.scrollTo({ top: el.scrollHeight }));
  await expect.poll(() => viewport.evaluate((el) => Math.round(el.scrollHeight - el.clientHeight - el.scrollTop))).toBeLessThanOrEqual(1);
}

/** Scroll each image figure into view in turn until `image` has loaded. */
async function scrollUntilLoaded(page: Page, image: ReturnType<Page["getByRole"]>): Promise<void> {
  const figures = page.getByTestId("media-image");
  for (let i = 0; i < (await figures.count()); i += 1) {
    if (await image.isVisible()) break;
    await figures.nth(i).scrollIntoViewIfNeeded();
  }
  await expect(image).toBeVisible();
}

for (const state of states) {
  test(`media turns render: image, voice turn, transcript, agent image (${state.name})`, async ({ page }) => {
    await openMedia(page, state.theme, state.width);
    await expect(page.getByText("living-room.png · ")).toBeVisible();
    await expect(page.getByTestId("transcript")).toHaveText("“Would a rug work better than a throw on the sofa in the first photo?”");
    await expect(page.locator("audio")).toHaveAttribute("src", /^blob:/);
    await expect(page.getByRole("button", { name: "Attach image or audio" })).toBeVisible();
    await noOverflow(page);
    await capture(page, `media-${state.name}`, true);
  });

  test(`attachment chips render (${state.name})`, async ({ page }) => {
    await openMedia(page, state.theme, state.width);
    await page.locator("input[type=file]").setInputFiles([
      { name: "sofa-closeup.png", mimeType: "image/png", buffer: TINY_PNG },
      { name: "note.wav", mimeType: "audio/wav", buffer: Buffer.from("RIFF\0\0\0\0WAVE") },
    ]);
    const chips = page.getByRole("list", { name: "Attachments" });
    await expect(chips).toContainText("sofa-closeup.png");
    await expect(chips).toContainText("note.wav");
    await expect(page.getByRole("button", { name: "Remove note.wav" })).toBeVisible();
    await noOverflow(page);
    await capture(page, `media-chips-${state.name}`, false);
  });

  test(`a refused file is named and its chip stays (${state.name})`, async ({ page }) => {
    await openMedia(page, state.theme, state.width);
    await page.locator("input[type=file]").setInputFiles([{ name: "photo.png", mimeType: "image/png", buffer: Buffer.from("not really a png") }]);
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByTestId("error")).toHaveText("Not sent: photo.png is not a file this agent accepts. Remove it and send again.");
    await expect(page.getByRole("button", { name: "Remove photo.png" })).toBeVisible();
    await noOverflow(page);
    await capture(page, `media-rejected-${state.name}`, false);
  });
}

test("a sent image shows at once, then from the media route; it opens full size", async ({ page }) => {
  await openMedia(page, "light", 1280);
  await page.locator("input[type=file]").setInputFiles([{ name: "sofa-closeup.png", mimeType: "image/png", buffer: TINY_PNG }]);
  await page.getByRole("combobox", { name: "Message or /command" }).fill("And this one?");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("img", { name: "Image sofa-closeup.png" })).toBeVisible();
  await expect(page.getByText("Noted. A rust rug and a warm lamp would do the most.")).toBeVisible();
  await page.getByRole("button", { name: "Open living-room.png full size" }).click();
  const dialog = page.getByRole("dialog", { name: "living-room.png" });
  await expect(dialog).toBeVisible();
  await capture(page, "media-dialog", false);
  await dialog.getByRole("button", { name: "Close" }).click();
  await expect(dialog).toBeHidden();
});

/** Voice (issue-38 task 26): recording, speaking, interrupted — T5. */
for (const state of states) {
  test(`hold to talk: recording, then the voice turn and its spoken reply (${state.name})`, async ({ page }) => {
    await openMedia(page, state.theme, state.width);
    const mic = page.getByRole("button", { name: "Hold to talk" });
    await expect(page.getByRole("button", { name: "Spoken replies" })).toHaveAttribute("aria-pressed", "true");
    await mic.hover();
    await page.mouse.down();
    await expect(mic).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("recording")).toContainText("Recording");
    await capture(page, `media-recording-${state.name}`, false);
    await page.waitForTimeout(1500);
    await page.mouse.up();
    await expect(mic).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByTestId("mic-live")).toHaveText("Sent");
    await expect(page.getByText("“Could the lamp be warmer too?”")).toBeVisible();
    await expect(page.getByRole("button", { name: "Stop speaking" })).toBeVisible();
    await expect(page.getByText("Speaking…")).toBeVisible();
    await noOverflow(page);
    await capture(page, `media-speaking-${state.name}`, false);
  });

  test(`a spoken reply that breaks off is interrupted, with Replay (${state.name})`, async ({ page }) => {
    await openMedia(page, state.theme, state.width, "&speech=broken");
    await page.getByRole("combobox", { name: "Message or /command" }).fill("And the curtains?");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Speech interrupted")).toBeVisible();
    await expect(page.getByRole("button", { name: "Replay spoken reply" })).toBeVisible();
    await noOverflow(page);
    await capture(page, `media-interrupted-${state.name}`, false);
  });
}
