import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";

const SAMPLES = resolve(process.cwd(), "..", "sample_datasets");
const PASSWORD = "e2e-password-123";

function watchForProblems(page: Page): string[] {
  const problems: string[] = [];
  page.on("pageerror", (error) => problems.push(`Page error: ${error.message}`));
  page.on("console", (message) => {
    const text = message.text();
    if (message.type() !== "error") return;
    // Expected HTTP refusals are reported by the browser as resource errors.
    if (/Failed to load resource/.test(text)) return;
    problems.push(`Console error: ${text}`);
  });
  return problems;
}

async function register(page: Page, name = "E2E Analyst"): Promise<string> {
  const email = `e2e-${Date.now()}-${Math.floor(Math.random() * 10000)}@example.com`;
  await page.goto("/register");
  await page.getByLabel("Full name").fill(name);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  return email;
}

async function uploadRetail(page: Page) {
  await page.goto("/datasets?upload=1");
  await page.getByTestId("file-input").setInputFiles(resolve(SAMPLES, "retail_sales.csv"));
  await expect(page.getByRole("button", { name: "Explore" })).toBeVisible({ timeout: 60_000 });
}

test("protected pages redirect to sign-in", async ({ page }) => {
  for (const path of ["/", "/explorer", "/reports", "/settings"]) {
    await page.goto(path);
    await expect(page).toHaveURL(/\/login$/);
  }
});

test("full analyst journey on the production build", async ({ page }) => {
  const problems = watchForProblems(page);
  const email = await register(page);

  await test.step("empty dashboard shows real zeros and useful actions", async () => {
    await expect(page.getByText("Start with some data")).toBeVisible();
    await expect(page.getByText("Total datasets")).toBeVisible();
  });

  await test.step("invalid files are rejected with a clear message", async () => {
    await page.goto("/datasets?upload=1");
    await page.getByTestId("file-input").setInputFiles({ name: "report.pdf.csv", mimeType: "text/csv", buffer: Buffer.from("%PDF-1.7 not a csv") });
    await expect(page.getByText(/binary and does not match/)).toBeVisible();
    await page.getByTestId("file-input").setInputFiles({ name: "tool.exe", mimeType: "application/octet-stream", buffer: Buffer.from("MZ") });
    await expect(page.getByText(/Unsupported file type/)).toBeVisible();
    await page.getByRole("button", { name: "Done" }).click();
  });

  await test.step("a CSV uploads, processes, and can be previewed", async () => {
    await uploadRetail(page);
    await expect(page.getByText(/6,030 rows, 13 columns/)).toBeVisible();
    await page.getByRole("button", { name: "Preview" }).click();
    await expect(page.getByRole("cell", { name: /ORD-/ }).first()).toBeVisible();
    await page.getByRole("button", { name: "Explore" }).click();
  });

  await test.step("the explorer shows, sorts, filters, and paginates real records", async () => {
    await expect(page).toHaveURL(/\/explorer/);
    await expect(page.getByText("6,030 rows")).toBeVisible();
    await page.getByRole("button", { name: "Next page" }).click();
    await expect(page.getByText(/Page 2 of/)).toBeVisible();
    await page.getByRole("button", { name: "revenue" }).click();
    await page.getByRole("button", { name: "revenue" }).click();
    await expect(page.getByRole("columnheader", { name: "revenue" })).toHaveAttribute("aria-sort", "descending");
    await page.getByRole("button", { name: /^Filters/ }).click();
    await page.getByRole("button", { name: "Add filter" }).click();
    await page.getByLabel("Filter column").selectOption("region");
    await page.getByLabel("Filter operator").selectOption("eq");
    await page.getByLabel("Value", { exact: true }).fill("Europe");
    await expect(page.getByText(/^\d[\d,]* rows$/)).not.toHaveText("6,030 rows");
    await page.getByRole("tab", { name: "Column profile" }).click();
    await page.getByRole("button", { name: /^revenue/ }).click();
    await expect(page.getByText("Std. deviation")).toBeVisible();
    await expect(page.getByText("Upper quartile")).toBeVisible();
    await page.getByRole("button", { name: /^region/ }).click();
    await expect(page.getByText("Most common values")).toBeVisible();
    await expect(page.getByText("Std. deviation")).toBeHidden();
    await page.getByRole("tab", { name: "Records" }).click();
  });

  await test.step("cleaning previews first and keeps the original version", async () => {
    await page.getByRole("link", { name: "Data Cleaning" }).click();
    await expect(page.getByText("Duplicate rows", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Add to plan" }).click();
    await page.getByRole("button", { name: "Preview effect" }).click();
    await expect(page.getByText(/Removes 30 duplicate rows/)).toBeVisible();
    await expect(page.getByText("Not saved")).toBeVisible();
    await page.getByRole("button", { name: "Save result" }).click();
    await page.getByRole("button", { name: "Confirm and save" }).click();
    await expect(page.getByText(/Saved as version 2/)).toBeVisible();
    await expect(page.getByRole("cell", { name: "6,000" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "6,030" })).toBeVisible();
  });

  await test.step("the analyst answers from calculations and says when it cannot", async () => {
    await page.getByRole("link", { name: "AI Data Analyst" }).click();
    await expect(page.getByText(/Demonstration mode\./)).toBeVisible();
    const box = page.getByLabel("Your question");
    await box.fill("Which month had the highest revenue?");
    await box.press("Enter");
    await expect(page.getByText(/The highest total revenue was in \d{4}-\d{2}/)).toBeVisible();
    await expect(page.getByText("Demonstration mode: no AI model")).toBeVisible();
    await expect(page.getByText("Supporting data")).toBeVisible();
    await box.fill("What will revenue be next year?");
    await box.press("Enter");
    await expect(page.getByText("I can't answer that from this dataset.")).toBeVisible();
    await expect(page.getByText("Could not be answered")).toBeVisible();
    await page.reload();
    await expect(page.getByText("I can't answer that from this dataset.")).toBeVisible();
  });

  await test.step("charts update with configuration and can be saved", async () => {
    await page.getByRole("link", { name: "Visualisations" }).click();
    await expect(page.locator(".recharts-bar-rectangle").first()).toBeVisible();
    const first = await page.locator(".recharts-bar-rectangle").count();
    await page.getByLabel("X axis").selectOption("product");
    await expect.poll(() => page.locator(".recharts-bar-rectangle").count()).not.toBe(first);
    for (const type of ["Line", "Area", "Pie", "Donut", "Scatter", "Histogram", "Box plot", "Bar"]) {
      await page.getByRole("radio", { name: type }).click();
      await page.waitForTimeout(450);
      await expect(page.getByRole("alert")).toHaveCount(0);
    }
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Visualisation saved.")).toBeVisible();
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "PNG" }).click();
    expect((await download).suggestedFilename()).toMatch(/\.png$/);
  });

  await test.step("anomaly detection finds and explains unusual records", async () => {
    await page.getByRole("link", { name: "Anomaly Detection" }).click();
    await page.getByRole("button", { name: "Run anomaly scan" }).first().click();
    await expect(page.getByText(/Scan finished/)).toBeVisible();
    await expect(page.getByText("not automatically errors or evidence of fraud")).toBeVisible();
    await page.getByRole("button", { name: "Inspect" }).first().click();
    await expect(page.getByText("Original records")).toBeVisible();
    await expect(page.getByRole("dialog").getByRole("table")).toBeVisible();
    await page.getByRole("dialog").getByRole("button", { name: "Close", exact: true }).first().click();
    await page.getByLabel("Investigation status").first().selectOption("investigating");
    await expect(page.getByLabel("Investigation status").first()).toHaveValue("investigating");
  });

  await test.step("reports generate and export", async () => {
    await page.getByRole("link", { name: "Reports" }).click();
    await page.getByRole("button", { name: "Generate report" }).first().click();
    await page.getByLabel("Report type").selectOption("sales_performance");
    await page.getByRole("button", { name: "Generate", exact: true }).click();
    await expect(page.getByText("Executive summary")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Limitations" })).toBeVisible();
    for (const [label, pattern] of [["PDF", /\.pdf$/], ["CSV", /\.csv$/], ["XLSX", /\.xlsx$/]] as const) {
      const download = page.waitForEvent("download");
      await page.getByRole("button", { name: label }).click();
      const file = await download;
      expect(file.suggestedFilename()).toMatch(pattern);
      if (label === "PDF") expect(readFileSync(await file.path()).subarray(0, 4).toString()).toBe("%PDF");
    }
  });

  await test.step("connections block internal addresses", async () => {
    await page.getByRole("link", { name: "Data Connections" }).click();
    await page.getByRole("button", { name: "Add connection" }).first().click();
    await page.getByLabel("Name", { exact: true }).fill("Internal");
    await page.getByLabel("URL").fill("http://169.254.169.254/latest/meta-data/");
    await page.getByRole("button", { name: "Save connection" }).click();
    await expect(page.getByText(/internal network addresses are not allowed/)).toBeVisible();
    await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();
  });

  await test.step("settings, dashboard metrics, search, and notifications work", async () => {
    await page.getByRole("link", { name: "Settings", exact: true }).click();
    await page.getByRole("tab", { name: "AI and privacy" }).click();
    await expect(page.getByText("What is shared with an AI provider")).toBeVisible();
    await page.getByRole("tab", { name: "Audit log" }).click();
    await expect(page.getByRole("cell", { name: "dataset.uploaded" })).toBeVisible();
    await page.getByRole("link", { name: "Overview", exact: true }).click();
    await expect(page.getByText("retail sales").first()).toBeVisible();
    await page.getByLabel("Search the workspace").fill("retail");
    await expect(page.getByRole("button", { name: /retail sales.*Dataset/i })).toBeVisible();
    await page.getByLabel(/^Notifications/).click();
    await expect(page.getByRole("heading", { name: "Notifications" })).toBeVisible();
    await page.getByLabel(/^Notifications/).click();
  });

  await test.step("deleting a dataset needs confirmation", async () => {
    await page.getByRole("link", { name: "My Datasets" }).click();
    await page.getByRole("button", { name: /^Delete retail sales/ }).click();
    await expect(page.getByText(/permanently deletes/)).toBeVisible();
    await page.getByRole("dialog").getByRole("button", { name: "Delete dataset" }).click();
    await expect(page.getByText("No datasets yet")).toBeVisible();
  });

  await test.step("logout ends the session", async () => {
    await page.getByRole("button", { name: "Log out" }).click();
    await expect(page).toHaveURL(/\/login$/);
    await page.goto("/");
    await expect(page).toHaveURL(/\/login$/);
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill("wrong-password-1");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByText("Incorrect email or password.")).toBeVisible();
  });

  expect(problems, "no script, CSP, or render errors").toEqual([]);
});

test("one user cannot open another user's dataset link", async ({ browser }) => {
  const first = await browser.newContext();
  const owner = await first.newPage();
  await register(owner, "Owner Person");
  await uploadRetail(owner);
  const link = await owner.getByRole("link", { name: "Explore" }).first().getAttribute("href");
  const second = await browser.newContext();
  const stranger = await second.newPage();
  await register(stranger, "Other Person");
  await stranger.goto(link!);
  await expect(stranger.getByText("No dataset available")).toBeVisible();
  await expect(stranger.getByRole("cell", { name: /ORD-/ })).toHaveCount(0);
  await first.close();
  await second.close();
});

test("every page fits a phone screen without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const problems = watchForProblems(page);
  await register(page, "Mobile User");
  await page.goto("/datasets");
  await page.getByRole("button", { name: "Load demo data" }).click();
  await expect(page.getByText("Retail Sales (Synthetic)")).toBeVisible();
  await expect(page.getByText("Ready")).toHaveCount(5, { timeout: 90_000 });
  for (const path of ["/", "/datasets", "/explorer", "/analyst", "/visualisations", "/cleaning", "/anomalies", "/reports", "/connections", "/settings"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `sideways scroll on ${path}`).toBeLessThanOrEqual(1);
  }
  await page.getByRole("button", { name: "Open menu" }).click();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  expect(problems).toEqual([]);
});
