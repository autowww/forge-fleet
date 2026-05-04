import { expect, test } from "@playwright/test";

/**
 * Guards admin “release identity” + overview tiles.
 * See docs/ADMIN-STATUS-OVERVIEW-DESIGN.md — missing git SHA breaks GitHub drift UX (not host thermals).
 */
test("admin overview: version API exposes git_sha; UI marks SHA present; overview tiles render", async ({
  page,
  request,
}) => {
  const verRes = await request.get("/v1/version");
  expect(verRes.ok()).toBe(true);
  const ver = await verRes.json();
  expect(ver.ok).toBe(true);
  expect(typeof ver.git_sha).toBe("string");
  expect(String(ver.git_sha).trim().length).toBeGreaterThanOrEqual(7);

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
  await expect(page.locator("#fleet-version-line")).toContainText("git", { timeout: 15_000 });

  await expect(page.locator("#fleet-git-remote-row")).toHaveAttribute("data-fleet-git-sha-state", "present", {
    timeout: 90_000,
  });

  await expect(page.locator("#fleet-tiles")).not.toContainText("Loading tiles", { timeout: 90_000 });
  await expect(page.locator("#fleet-cpu-value")).toBeVisible();
  await expect(page.locator("#fleet-mem-val")).toBeVisible();
});
