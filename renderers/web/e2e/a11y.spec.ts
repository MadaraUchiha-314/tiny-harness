import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("the prototype state has no axe violations", async ({ page }) => {
  await page.goto("/?fixture=prototype");
  await expect(page.getByTestId("state")).toHaveText("INPUT_REQUIRED");
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(results.violations).toEqual([]);
});

test("every control is reachable by keyboard", async ({ page }) => {
  await page.goto("/?fixture=prototype");
  const reached: string[] = [];
  for (let i = 0; i < 40; i += 1) {
    await page.keyboard.press("Tab");
    const label = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el) return "";
      const name = el.getAttribute("aria-label") || el.id || el.textContent?.trim().slice(0, 20) || "";
      return `${el.tagName.toLowerCase()}:${name}`;
    });
    reached.push(label);
  }
  expect(reached.some((l) => l.includes("Cancel task"))).toBe(true);
  expect(reached.some((l) => l.startsWith("textarea"))).toBe(true);
  expect(reached.some((l) => l.includes("trigger-task") || l === "button:Task")).toBe(true);
  expect(reached.some((l) => l.startsWith("button:Send"))).toBe(true);
  await page.getByRole("tab", { name: "Plan" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("tabpanel", { name: "Plan" })).toBeVisible();
});

test("the task controls and the command listbox have no axe violations", async ({ page }) => {
  await page.goto("/?fixture=controls");
  await expect(page.getByTestId("sub-state")).toHaveText("awaiting next message");
  expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze()).violations).toEqual([]);
  await page.getByRole("combobox", { name: "Message or /command" }).fill("/");
  await expect(page.getByRole("listbox", { name: "Commands" })).toBeVisible();
  expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze()).violations).toEqual([]);
});

test("Complete, Cancel, the listbox, sub-task links and ← Parent are keyboard-reachable", async ({ page }) => {
  await page.goto("/?fixture=controls");
  await expect(page.getByTestId("sub-state")).toHaveText("awaiting next message");
  const focused = () => page.evaluate(() => document.activeElement?.textContent?.trim() ?? "");
  /** Tab from the top of the page until `match` has the focus. */
  const tabTo = async (match: (label: string) => boolean): Promise<boolean> => {
    await page.locator("body").focus();
    for (let i = 0; i < 40; i += 1) {
      await page.keyboard.press("Tab");
      if (match(await focused())) return true;
    }
    return false;
  };
  const reached: string[] = [];
  for (let i = 0; i < 30; i += 1) {
    await page.keyboard.press("Tab");
    reached.push(await focused());
  }
  expect(reached).toContain("Complete");
  expect(reached).toContain("Cancel task");

  // The combobox: options are reached with the arrow keys and accepted with Enter.
  const box = page.getByRole("combobox", { name: "Message or /command" });
  await box.focus();
  await page.keyboard.type("/");
  await expect(box).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await expect(box).toHaveAttribute("aria-activedescendant", "cmd-sub-task");
  await page.keyboard.press("Enter");
  await expect(box).toHaveValue("/sub-task ");
  await page.keyboard.type("Draft the reply");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("command")).toContainText("Created sub-task");

  // The new sub-task's link and, once it is open, ← Parent, by keyboard alone.
  expect(await tabTo((label) => label.startsWith("5b1d")), "the sub-task link is reachable with Tab").toBe(true);
  await page.keyboard.press("Enter");
  const parent = page.getByTestId("parent");
  await expect(parent).toBeVisible();
  expect(await tabTo((label) => label === "← Parent"), "← Parent is reachable with Tab").toBe(true);
  await page.keyboard.press("Enter");
  await expect(parent).toHaveCount(0);
});

/** Issue-38 (T9): the multimodal states and the keyboard-only attach flow. */
const axe = async (page: import("@playwright/test").Page) =>
  (await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze()).violations;

test("the media states have no axe violations", async ({ page }) => {
  await page.goto("/?fixture=media");
  await expect(page.getByRole("img", { name: "Image living-room.png" })).toBeVisible();
  await expect(page.locator("audio")).toHaveAttribute("src", /^blob:/);
  expect(await axe(page)).toEqual([]);
  await page.locator("input[type=file]").setInputFiles([{ name: "photo.png", mimeType: "image/png", buffer: Buffer.from("not a png") }]);
  await expect(page.getByRole("button", { name: "Remove photo.png" })).toBeVisible();
  expect(await axe(page)).toEqual([]);
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByTestId("error")).toContainText("Not sent: photo.png");
  expect(await axe(page)).toEqual([]);
});

test("attach by keyboard: the paperclip, /attach, and removing a chip", async ({ page }) => {
  // Listen before the page loads, so file-chooser interception is on before any key press.
  const choosers: import("@playwright/test").FileChooser[] = [];
  page.on("filechooser", (chooser) => choosers.push(chooser));
  const nextChooser = async () => {
    await expect.poll(() => choosers.length).toBeGreaterThan(0);
    return choosers.shift()!;
  };
  await page.goto("/?fixture=media");
  await expect(page.getByRole("img", { name: "Image living-room.png" })).toBeVisible();
  const clip = page.getByRole("button", { name: "Attach image or audio" });
  await clip.focus();
  await page.keyboard.press("Enter");
  const chooser = await nextChooser();
  await chooser.setFiles([{ name: "first.png", mimeType: "image/png", buffer: Buffer.from("x") }]);
  await expect(page.getByRole("button", { name: "Remove first.png" })).toBeVisible();

  const box = page.getByRole("combobox", { name: "Message or /command" });
  await box.focus();
  await page.keyboard.type("/att");
  await expect(box).toHaveAttribute("aria-activedescendant", "cmd-attach");
  await page.keyboard.press("Enter");
  await expect(box).toHaveValue("/attach ");
  await expect(box).toHaveAttribute("aria-expanded", "false");
  await page.keyboard.press("Enter");
  const second = await nextChooser();
  await second.setFiles([{ name: "second.png", mimeType: "image/png", buffer: Buffer.from("x") }]);
  await expect(page.getByRole("button", { name: "Remove second.png" })).toBeVisible();
  await expect(box).toHaveValue("");

  await page.getByRole("button", { name: "Remove first.png" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Remove first.png" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Remove second.png" })).toBeVisible();
});

test("the voice states have no axe violations, and the mic, Stop and Replay work by keyboard", async ({ page }) => {
  await page.goto("/?fixture=media");
  await expect(page.getByRole("img", { name: "Image living-room.png" })).toBeVisible();
  const mic = page.getByRole("button", { name: "Hold to talk" });
  const live = page.getByTestId("mic-live");

  // Space starts, Enter stops and sends.
  await mic.focus();
  await page.keyboard.press(" ");
  await expect(mic).toHaveAttribute("aria-pressed", "true");
  await expect(live).toHaveText("Recording");
  expect(await axe(page)).toEqual([]);
  await page.waitForTimeout(1500);
  await page.keyboard.press("Enter");
  await expect(mic).toHaveAttribute("aria-pressed", "false");
  await expect(live).toHaveText("Sent");

  // The reply speaks: Stop by keyboard, then Replay by keyboard.
  const stop = page.getByRole("button", { name: "Stop speaking" });
  await expect(stop).toBeVisible();
  expect(await axe(page)).toEqual([]);
  await stop.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText(/^Stopped at \d:\d\d$/)).toBeVisible();
  const replay = page.getByRole("button", { name: "Replay spoken reply" });
  await replay.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Stop speaking" })).toBeVisible();

  // Enter starts, Space stops.
  await mic.focus();
  await page.keyboard.press("Enter");
  await expect(mic).toHaveAttribute("aria-pressed", "true");
  await page.waitForTimeout(1500);
  await page.keyboard.press(" ");
  await expect(live).toHaveText("Sent");
});

test("an interrupted spoken reply has no axe violations", async ({ page }) => {
  await page.goto("/?fixture=media&speech=broken");
  await expect(page.getByRole("img", { name: "Image living-room.png" })).toBeVisible();
  await page.getByRole("combobox", { name: "Message or /command" }).fill("And the curtains?");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Speech interrupted")).toBeVisible();
  expect(await axe(page)).toEqual([]);
});
