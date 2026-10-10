import { expect, test } from "@playwright/test";

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
    await expect(page.getByTestId("help")).toBeVisible();
    await expect(page.getByTestId("placeholder")).toContainText("application/vnd.example.calendar+json");
    await expect(page).toHaveScreenshot(`${state.name}.png`, { fullPage: true, maxDiffPixelRatio: 0.02 });
  });
}

test("the plan tab shows the DAG", async ({ page }) => {
  await page.goto("/?fixture=prototype");
  await page.getByRole("tab", { name: "Plan" }).click();
  await expect(page.getByRole("tabpanel", { name: "Plan" })).toContainText("Agree resolution with customer");
  await expect(page).toHaveScreenshot("plan.png", { maxDiffPixelRatio: 0.02 });
});
