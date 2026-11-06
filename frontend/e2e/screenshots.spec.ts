import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

/**
 * Captures the README screenshots from the running application, using only synthetic demonstration
 * data and a placeholder account. Run with: npx playwright test e2e/screenshots.spec.ts
 */
const OUT = resolve(process.cwd(), "..", "docs", "screenshots");

test("capture documentation screenshots", async ({ page }) => {
  test.setTimeout(240_000);
  const shot = async (name: string) => {
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);
    await page.screenshot({ path: resolve(OUT, `${name}.png`) });
  };

  await page.goto("/register");
  await page.getByLabel("Full name").fill("Demo Analyst");
  await page.getByLabel("Email").fill(`demo-${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("demo-password-123");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();

  await page.goto("/datasets");
  await page.getByRole("button", { name: "Load demo data" }).click();
  await expect(page.getByText("Ready")).toHaveCount(5, { timeout: 120_000 });
  await expect.poll(async () => (await page.request.get("/api/reports")).json(), { timeout: 60_000 }).not.toEqual([]);

  const retailLink = await page.getByRole("link", { name: "Retail Sales (Synthetic)", exact: true }).getAttribute("href");
  const datasetId = new URL(retailLink!, "http://x").searchParams.get("dataset");
  const ask = async (question: string) => {
    const box = page.getByLabel("Your question");
    await box.fill(question);
    await box.press("Enter");
  };

  // Some real activity for the dashboard's chart and tables.
  await page.goto(`/analyst?dataset=${datasetId}`);
  await ask("What were the five best-performing products by revenue?");
  await expect(page.getByText("Could not be answered").or(page.getByText("Calculated from your data"))).toBeVisible();
  await expect(page.getByText("Key findings")).toBeVisible();
  await page.waitForTimeout(600);
  await page.evaluate(() => window.scrollTo(0, 0));
  await shot("05-ai-data-analyst");

  await page.goto("/");
  await expect(page.getByText("Records analysed")).toBeVisible();
  await shot("01-dashboard");

  await page.goto("/datasets?upload=1");
  await page.getByTestId("file-input").setInputFiles(resolve(process.cwd(), "..", "sample_datasets", "product_performance.csv"));
  await expect(page.getByRole("button", { name: "Explore" }).first()).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "Preview" }).first().click();
  await expect(page.getByText(/^Preview:/)).toBeVisible();
  await shot("02-dataset-upload");

  await page.goto(`/explorer?dataset=${datasetId}`);
  await expect(page.getByRole("cell", { name: /ORD-/ }).first()).toBeVisible();
  await shot("03-data-explorer");

  await page.goto(`/cleaning?dataset=${datasetId}`);
  await expect(page.getByRole("button", { name: "Add fix" }).first()).toBeVisible();
  await page.getByRole("button", { name: "Add fix" }).first().click();
  await page.getByRole("button", { name: "Add to plan" }).click();
  await page.getByRole("button", { name: "Preview effect" }).click();
  await expect(page.getByText("Not saved")).toBeVisible();
  await shot("04-data-cleaning");

  await page.goto(`/visualisations?dataset=${datasetId}`);
  await expect(page.locator(".recharts-bar-rectangle").first()).toBeVisible();
  await page.getByLabel("Group by").selectOption("category");
  await page.waitForTimeout(700);
  await shot("06-visualisation-studio");

  await page.goto(`/anomalies?dataset=${datasetId}`);
  await expect(page.getByLabel("Investigation status").first()).toBeVisible();
  await shot("07-anomaly-detection");

  await page.goto("/reports");
  await page.getByRole("button", { name: "Generate report" }).first().click();
  await page.getByRole("dialog").locator("select").first().selectOption(datasetId!);
  await page.getByLabel("Report type").selectOption("sales_performance");
  await page.getByRole("button", { name: "Generate", exact: true }).click();
  await expect(page.getByText("Executive summary")).toBeVisible();
  await shot("08-reports");
});
