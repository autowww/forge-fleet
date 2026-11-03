#!/usr/bin/env node
/**
 * Seed forgeFleetAdminToken in the operator Edge profile for a Fleet admin origin.
 * Env: ADMIN_ORIGIN (e.g. https://granite.forgedc.net), FLEET_ADMIN_BEARER_TOKEN,
 *      EDGE_CDP_URL (default http://127.0.0.1:9222)
 */
import { chromium } from "playwright";

const origin = (process.env.ADMIN_ORIGIN || "").trim().replace(/\/$/, "");
const token = (process.env.FLEET_ADMIN_BEARER_TOKEN || process.env.FORGE_FLEET_BEARER_TOKEN || "").trim();
const cdp = (process.env.EDGE_CDP_URL || "http://127.0.0.1:9222").trim();

if (!origin) {
  console.error("missing ADMIN_ORIGIN");
  process.exit(2);
}
if (!token) {
  console.error("missing FLEET_ADMIN_BEARER_TOKEN");
  process.exit(2);
}

const browser = await chromium.connectOverCDP(cdp);
const contexts = browser.contexts();
if (!contexts.length) {
  console.error("no Edge contexts on CDP");
  process.exit(1);
}
const context = contexts[0];
const page = await context.newPage();
await page.goto(`${origin}/admin/`, { waitUntil: "domcontentloaded", timeout: 120_000 });
await page.evaluate(
  (t) => {
    localStorage.setItem("forgeFleetAdminToken", t);
    localStorage.removeItem("forgeFleetActiveRemotePeer");
    localStorage.setItem("fleet_welcome_seen_v1", "1");
  },
  token
);
const probe = await page.evaluate(async () => {
  const h = { Accept: "application/json", Authorization: "Bearer " + localStorage.getItem("forgeFleetAdminToken") };
  const r = await fetch("/v1/admin/snapshot?jobs_limit=1&jobs_offset=0", { headers: h, cache: "no-store" });
  return r.status;
});
console.log(`seeded ${origin} snapshot HTTP ${probe}`);
await page.close();
process.exit(probe === 200 ? 0 : 1);
