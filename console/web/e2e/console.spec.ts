import { expect, test, type Page } from "@playwright/test";

// Runs against the repository's committed output/ — real STATUTE data, read-only.
const PR = "synthesis@2026-07-29T16.06.14.998Z";

function watchErrors(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  return errors;
}

test("home answers what STATUTE is doing within seconds", async ({ page }) => {
  const errors = watchErrors(page);
  const t = Date.now();
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Stages" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Needs attention" })).toBeVisible();
  expect(Date.now() - t).toBeLessThan(5000);
  const cells = page.locator('section[aria-labelledby="stages-h"] > ol > li');
  await expect(cells).toHaveCount(8);
  await expect(page.getByText("Recorded source path not found for 7 of 7 files")).toBeVisible();
  await expect(page.getByText("2 stages do not record every input they consumed")).toBeVisible();
  await expect(page.getByText(PR)).toBeVisible();
  await expect(page.getByText(/Re-run 8 stage\(s\) starting at 01_inventory/)).toBeVisible();
  expect(errors).toEqual([]);
});

test("every dashboard tab renders real data without console errors", async ({ page }) => {
  const errors = watchErrors(page);
  const tabs: [string, string | RegExp][] = [
    ["/agents", "1_inventory_plsql"], ["/artifacts", "inventory-artifact.json"], ["/trace", "124 statements"],
    ["/testing", "QUALITY SCORE"], ["/workflow", /Stage lineage/], ["/diagrams", "Process flow: SP_TRANSFER_FUNDS"],
    ["/timeline", "Stage 1: Inventory completed"], ["/rules", "41 of 41 rules"], ["/data", "LOAN_MASTER"], ["/state", "generated_at"],
  ];
  for (const [path, text] of tabs) {
    await page.goto(path);
    await expect(page.locator(`nav[aria-label="Dashboard sections"] [aria-current="page"]`)).toHaveAttribute("href", path);
    await expect(page.getByText(text).first()).toBeVisible({ timeout: 10000 });
  }
  expect(errors).toEqual([]);
});

test("the BRD opens in a modal with a table of contents and closes on Escape", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "View BRD" }).click();
  const dialog = page.getByRole("dialog", { name: "Business Requirements Document" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("navigation", { name: "BRD contents" }).getByRole("button", { name: "5. Business Rules Catalogue" }).click();
  await expect(dialog.getByRole("heading", { name: "5. Business Rules Catalogue" })).toBeInViewport();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
});

test("theme toggle switches to light and is remembered", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Light theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: "Dark theme" }).click();
});

test("the layout fits a phone screen without horizontal scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Stages" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.getByRole("button", { name: "Expand sidebar" }).click();
  await page.getByRole("link", { name: /^Stage 2, Parser/ }).click();
  await expect(page.getByRole("button", { name: "Expand sidebar" })).toBeVisible();   // closes after navigating
});

test("deep links with run versions load (dots in the last path segment)", async ({ page }) => {
  await page.goto(`/runs/${PR}`);
  await expect(page.getByRole("heading", { name: "Lineage" })).toBeVisible();
  await expect(page.getByText(/^Between invocations \d/)).toBeVisible();
  await page.goto("/stages/02_parser/runs/2026-07-29T16.05.37.101Z?tab=items");
  await expect(page.getByRole("tab", { name: "Items" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("link", { name: "PROC-.SP_TRANSFER_FUNDS" })).toBeVisible();
});

test("a requirement traces to its source line in three clicks or fewer", async ({ page }) => {
  await page.goto("/evidence?q=BR-002");
  await page.getByRole("link", { name: /BR-002 · Enforce From Balance/ }).click();         // 1
  await expect(page.getByText("PROVENANCE PATH", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Show source lines" }).click();                    // 2
  const focus = page.locator('[aria-current="true"]');
  await expect(focus).toContainText("79");
  await expect(focus).toContainText("RAISE e_insufficient_balance");
});

test("stage-run tabs are keyboard navigable", async ({ page }) => {
  await page.goto("/stages/05_rules/runs/2026-07-29T16.06.06.566Z");
  await page.getByRole("tab", { name: "Summary" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: /Inputs/ })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByText("not recorded by this run")).toBeVisible();      // 04_logic provenance hole
});

test("findings lens is held in the URL", async ({ page }) => {
  await page.goto("/findings?category=review");
  await expect(page.getByRole("tab", { name: /Review/ })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByText("Needs business confirmation: Enforce Balance below 1,000,000 (BR-039)")).toBeVisible();
});

test("health reports the stale agent instruction and the unreachable source path", async ({ page }) => {
  await page.goto("/health");
  await expect(page.getByText(/--output \.\/checkpoints\//)).toBeVisible();
  await expect(page.getByText("0 of 7 files reachable at their recorded path; 7 located in total")).toBeVisible();
});

test("artifact previews render generated diagrams in a sandboxed frame", async ({ page }) => {
  await page.goto("/stages/06_diagram/runs/2026-07-29T16.06.14.882Z?tab=outputs");
  await page.getByRole("button", { name: "diagrams/state_ACCOUNTS.mmd" }).click();
  const frame = page.locator("iframe[title='diagrams/state_ACCOUNTS.mmd']");
  await expect(frame).toBeVisible({ timeout: 15000 });
  await expect(frame).toHaveAttribute("sandbox", "");
  await page.keyboard.press("Escape");
  await expect(frame).toBeHidden();
});

test("the API is read-only and rejects foreign hosts", async ({ request }) => {
  expect((await request.post("/api/v1/status")).status()).toBe(405);
  expect((await request.get("/api/v1/status", { headers: { Host: "attacker.example" } })).status()).toBe(421);
  const r = await request.get("/api/v1/status");
  expect(r.headers()["content-security-policy"]).toContain("default-src 'self'");
  expect(JSON.stringify(await r.json())).not.toMatch(/[A-Za-z]:\\\\(Users|Virtusa)/);
});

test("key pages have no serious or critical accessibility violations (axe, WCAG 2.2 AA)", async ({ page }) => {
  test.setTimeout(180000);   // 17 pages, each fully analysed
  const { default: AxeBuilder } = await import("@axe-core/playwright");
  const found: string[] = [];
  for (const path of ["/", `/runs/${PR}`, "/stages/02_parser/runs/2026-07-29T16.05.37.101Z", "/findings", "/evidence/rule/BR-002", "/health", "/events",
    "/agents", "/artifacts", "/trace", "/testing", "/workflow", "/diagrams", "/timeline", "/rules", "/data", "/state"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    // Diagram frames are sandboxed with scripts disabled, so axe cannot be injected into them.
    const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).options({ iframes: false }).exclude("iframe").analyze();
    for (const v of r.violations.filter((x) => x.impact === "serious" || x.impact === "critical")) {
      found.push(`${path}: ${v.id} (${v.impact}) × ${v.nodes.length} — ${v.nodes.slice(0, 2).map((n) => n.target.join(" ")).join(" | ")}`);
    }
  }
  expect(found, found.join("\n")).toEqual([]);
});
