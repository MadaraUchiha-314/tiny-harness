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
  expect(reached.some((l) => l.includes("tab-task"))).toBe(true);
  expect(reached.some((l) => l.startsWith("button:Send"))).toBe(true);
  await page.getByRole("tab", { name: "Plan" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("tabpanel", { name: "Plan" })).toBeVisible();
});
