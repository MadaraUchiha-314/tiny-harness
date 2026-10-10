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
