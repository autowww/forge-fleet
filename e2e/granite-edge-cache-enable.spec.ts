import { expect, test } from "@playwright/test";

/**
 * Enables Cloudflare edge-cache orchestration on a remote Fleet host (Granite) through
 * local /admin/ Settings → Edge, using the remote-peers ui-settings proxy.
 *
 * Required env:
 *   FORGE_FLEET_BASE_URL, FORGE_FLEET_BEARER_TOKEN — remote Granite Fleet
 *   CLOUDFLARE_API_TOKEN, CF_ZONE_ID — Cloudflare Cache Rules edit
 *   FLEET_BEARER_TOKEN — local laptop Fleet admin (defaults to remote bearer)
 * Optional: FORGE_FLEET_REMOTE_PEER_ID (default granite)
 */
test("remote Granite: enable edge cache via Fleet admin Playwright", async ({ page, request }) => {
  const remoteUrl = (process.env.FORGE_FLEET_BASE_URL || "").trim().replace(/\/$/, "");
  const remoteToken = (process.env.FORGE_FLEET_BEARER_TOKEN || "").trim();
  const cfToken = (process.env.CLOUDFLARE_API_TOKEN || "").trim();
  const zoneId = (process.env.CF_ZONE_ID || "").trim();
  const localToken = (process.env.FLEET_BEARER_TOKEN || remoteToken).trim();
  const peerId = (process.env.FORGE_FLEET_REMOTE_PEER_ID || "granite").trim();

  test.skip(
    !remoteUrl || !remoteToken || !cfToken || !zoneId || !localToken,
    "Set FORGE_FLEET_BASE_URL, FORGE_FLEET_BEARER_TOKEN, CLOUDFLARE_API_TOKEN, CF_ZONE_ID",
  );

  const peerRes = await request.put(`/v1/remote-peers/${encodeURIComponent(peerId)}`, {
    headers: {
      Authorization: `Bearer ${localToken}`,
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    data: {
      label: "Granite Fleet",
      base_url: remoteUrl,
      bearer_token: remoteToken,
    },
  });
  expect(peerRes.ok()).toBeTruthy();

  await page.addInitScript(
    ({ t, pid }: { t: string; pid: string }) => {
      localStorage.setItem("forgeFleetAdminToken", t);
      localStorage.setItem("forgeFleetActiveRemotePeer", pid);
    },
    { t: localToken, pid: peerId },
  );

  await page.goto("/admin/");
  await expect(page.locator("#fleet-version-line")).not.toContainText("Loading version", {
    timeout: 90_000,
  });

  await page.getByRole("button", { name: "Settings…" }).click();
  await page.locator("#fleet-connect-wizard-steps [data-fleet-settings-tab='edge']").click();

  await page.locator("#fleet-edge-cache-orchestrate").check();
  await page.locator("#fleet-edge-cache-enabled").check();
  await page.locator("#fleet-edge-cache-zone-id").fill(zoneId);
  await page.locator("#fleet-edge-cache-token").fill(cfToken);
  await page.locator("#fleet-edge-cache-save").click();

  const syncOut = page.locator("#fleet-edge-cache-sync-out");
  await expect(syncOut).not.toContainText("not_orchestrator", { timeout: 120_000 });
  await expect(syncOut).toContainText('"ok": true', { timeout: 120_000 });

  await page.locator("#fleet-edge-cache-sync").click();
  await expect(syncOut).toContainText('"ok": true', { timeout: 120_000 });
});
