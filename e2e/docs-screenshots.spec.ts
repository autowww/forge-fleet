import * as fs from "fs";
import * as path from "path";
import { expect, test } from "@playwright/test";

/**
 * Regenerates handbook imagery under docs/assets/ (see docs/assets/README.md).
 * Playwright webServer targets http://127.0.0.1:19876 (see playwright.config.ts).
 */
test("docs: capture /admin/ overview screenshot", async ({ page }) => {
  const outDir = path.join(__dirname, "..", "docs", "assets");
  const outFile = path.join(outDir, "admin-overview.png");
  fs.mkdirSync(outDir, { recursive: true });

  const token = (process.env.FLEET_BEARER_TOKEN || "").trim();
  if (token) {
    await page.addInitScript((t: string) => {
      localStorage.setItem("forgeFleetAdminToken", t);
    }, token);
  }

  await page.goto("/admin/");
  await expect(page.locator("#fleet-version-line")).not.toContainText("Loading version", {
    timeout: 90_000,
  });
  await expect(page.locator("#fleet-tiles")).not.toContainText("Loading tiles", { timeout: 90_000 });

  await page.screenshot({ path: outFile, fullPage: true });
});
