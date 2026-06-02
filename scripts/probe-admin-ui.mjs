#!/usr/bin/env node
/**
 * Probe admin UI boot: script HTTP status + whether version/tiles leave loading state.
 * Usage: FLEET_E2E_BASE=http://127.0.0.1:19876 node scripts/probe-admin-ui.mjs
 */
import { chromium } from "playwright";

const base = process.env.FLEET_E2E_BASE || "http://127.0.0.1:19876";
const rev = process.env.FLEET_BISECT_REV || process.env.GIT_COMMIT || "?";

const probePaths = [
  "/admin/static/app-part1.js",
  "/admin/static/app-part6.js",
  "/admin/static/app-src/part3/telemetry-x-axis.js",
  "/admin/static/app-src/part6/snapshot-load.js",
  "/admin/static/app-src/part6/boot-close.js",
  "/admin/ks/js/forge-theme.js",
];

const out = { rev, base, scripts: {}, networkFailed: [], consoleErrors: [], ui: {} };

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();

page.on("requestfailed", (req) => {
  if (req.url().includes("/admin/")) {
    out.networkFailed.push({ url: req.url(), err: req.failure()?.errorText || "failed" });
  }
});
page.on("console", (msg) => {
  if (msg.type() === "error") out.consoleErrors.push(msg.text().slice(0, 300));
});

for (const path of probePaths) {
  const r = await page.request.get(base + path);
  out.scripts[path] = r.status();
}

await page.goto(`${base}/admin/`, { waitUntil: "networkidle", timeout: 60_000 });
await page.waitForTimeout(6_000);

out.ui.versionLine = (await page.locator("#fleet-version-line").innerText()).trim();
out.ui.tilesText = (await page.locator("#fleet-tiles").innerText()).trim().slice(0, 100);
out.ui.cpuVisible = await page.locator("#fleet-cpu-value").isVisible().catch(() => false);

const ver = await page.request.get(`${base}/v1/version`);
out.apiVersion = ver.ok() ? await ver.json() : { status: ver.status() };

await browser.close();

out.ok =
  !out.ui.versionLine.includes("Loading version") &&
  !out.ui.tilesText.includes("Loading tiles") &&
  out.ui.cpuVisible;

console.log(JSON.stringify(out, null, 2));
process.exit(out.ok ? 0 : 1);
