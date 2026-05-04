import { expect, test } from "@playwright/test";

/**
 * Guards admin “release identity” + overview tiles (including horizontal KPI row layout).
 * See docs/ADMIN-STATUS-OVERVIEW-DESIGN.md.
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

  const tiles = page.locator("#fleet-tiles");
  const rowStyle = await tiles.evaluate((el) => {
    const s = getComputedStyle(el);
    return { display: s.display, flexDirection: s.flexDirection };
  });
  expect(rowStyle.display).toBe("flex");
  expect(rowStyle.flexDirection).toBe("row");

  const directTiles = tiles.locator(":scope > .fleet-tile");
  expect(await directTiles.count()).toBeGreaterThanOrEqual(4);
  const xs = await directTiles.evaluateAll((els) =>
    Array.from(els)
      .slice(0, 3)
      .map((e) => e.getBoundingClientRect().left),
  );
  expect(xs.length).toBeGreaterThanOrEqual(2);
  expect(xs[1]).toBeGreaterThan(xs[0]);
});
