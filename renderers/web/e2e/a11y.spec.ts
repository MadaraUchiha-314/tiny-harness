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
