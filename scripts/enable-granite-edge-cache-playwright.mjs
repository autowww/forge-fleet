#!/usr/bin/env node
/**
 * Enable remote Fleet edge-cache via local /admin/ (Settings → Edge).
 * Env: FORGE_FLEET_BASE_URL, FORGE_FLEET_BEARER_TOKEN, CLOUDFLARE_API_TOKEN,
 *      CF_ZONE_ID (optional default forgedc zone), FLEET_BEARER_TOKEN, FORGE_FLEET_REMOTE_PEER_ID.
 */
import { chromium } from "playwright";

const remoteUrl = (process.env.FORGE_FLEET_BASE_URL || "").trim().replace(/\/$/, "");
const remoteToken = (process.env.FORGE_FLEET_BEARER_TOKEN || "").trim();
const cfToken = (process.env.CLOUDFLARE_API_TOKEN || "").trim();
const zoneId = (process.env.CF_ZONE_ID || "a930a3d1ec96b9bcaa0ab388ddad6274").trim();
const localToken = (process.env.FLEET_BEARER_TOKEN || "").trim();
const peerId = (process.env.FORGE_FLEET_REMOTE_PEER_ID || "granite").trim();
const localBase = (process.env.FLEET_ADMIN_BASE_URL || "http://127.0.0.1:18766").replace(/\/$/, "");

function need(name) {
  console.error(`missing ${name}`);
  process.exit(2);
}

if (!remoteUrl) need("FORGE_FLEET_BASE_URL");
if (!remoteToken) need("FORGE_FLEET_BEARER_TOKEN");
if (!cfToken) need("CLOUDFLARE_API_TOKEN");
if (!localToken) need("FLEET_BEARER_TOKEN");

const peerRes = await fetch(`${localBase}/v1/remote-peers/${encodeURIComponent(peerId)}`, {
  method: "PUT",
  headers: {
    Authorization: `Bearer ${localToken}`,
    Accept: "application/json",
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    label: "Granite Fleet",
    base_url: remoteUrl,
    bearer_token: remoteToken,
  }),
});
if (!peerRes.ok) {
  console.error("remote peer PUT failed", peerRes.status, await peerRes.text());
  process.exit(1);
}

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
await page.addInitScript(
  ({ t, pid }) => {
    localStorage.setItem("forgeFleetAdminToken", t);
    localStorage.setItem("forgeFleetActiveRemotePeer", pid);
    localStorage.setItem("fleet_welcome_seen_v1", "1");
  },
  { t: localToken, pid: peerId },
);

await page.goto(`${localBase}/admin/`, { waitUntil: "domcontentloaded" });
await page.locator("#fleet-version-line").waitFor({ state: "visible", timeout: 90_000 });
await page.getByRole("button", { name: "Settings…" }).click();
await page.locator("#fleet-connect-wizard-offcanvas").waitFor({ state: "visible" });
await page.locator("#fleet-connect-wizard-steps [data-fleet-settings-tab='edge']").click();

await page.locator("#fleet-edge-cache-orchestrate").check();
await page.locator("#fleet-edge-cache-enabled").check();
await page.locator("#fleet-edge-cache-zone-id").fill(zoneId);
await page.locator("#fleet-edge-cache-token").fill(cfToken);
await page.locator("#fleet-edge-cache-save").click();

const syncOut = page.locator("#fleet-edge-cache-sync-out");
await syncOut.waitFor({ state: "visible" });
for (let i = 0; i < 90; i++) {
  const text = await syncOut.textContent();
  if (
    text &&
    (text.includes('"pending": true') ||
      (text.includes('"ok": true') && !text.includes("not_orchestrator")))
  ) {
    break;
  }
  await page.waitForTimeout(2000);
}
const settingsRes = await fetch(
  `${localBase}/v1/remote-peers/${encodeURIComponent(peerId)}/operator/ui-settings`,
  { headers: { Authorization: `Bearer ${localToken}`, Accept: "application/json" } },
);
const settingsJson = await settingsRes.json();
const cache = settingsJson?.settings?.edge?.cache || {};
if (!settingsRes.ok || !cache.orchestrate || !cache.enabled) {
  console.error("remote cache policy not enabled:", JSON.stringify(cache));
  await browser.close();
  process.exit(1);
}
console.log("remote edge cache policy saved (orchestrate + enabled)");

await page.locator("#fleet-edge-cache-sync").click();
for (let i = 0; i < 60; i++) {
  const text = await syncOut.textContent();
  if (text && text.includes('"ok": true')) {
    console.log("edge-cache sync ok");
    await browser.close();
    process.exit(0);
  }
  await page.waitForTimeout(2000);
}
console.error("manual sync failed:", await syncOut.textContent());
await browser.close();
process.exit(1);
