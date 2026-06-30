#!/usr/bin/env node
/**
 * Fleet /admin/ UI smoke — console errors, snapshot load, tabs, telemetry modal.
 * usage: node scripts/smoke-admin-ui.mjs [--base http://127.0.0.1:18766]
 */
import process from 'node:process';

const base = (() => {
  const i = process.argv.indexOf('--base');
  return (i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : 'http://127.0.0.1:18766').replace(/\/$/, '');
})();

const issues = [];
const consoleErrors = [];
const failedRequests = [];

function fail(msg) {
  issues.push(msg);
  console.error('FAIL:', msg);
}

function pass(msg) {
  console.log('ok:', msg);
}

async function main() {
  let chromium;
  try {
    ({ chromium } = await import('playwright'));
  } catch {
    fail('playwright not installed — run: npm install -D playwright && npx playwright install chromium');
    process.exit(2);
  }

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      const t = msg.text();
      if (/favicon|Failed to load resource.*404/.test(t)) return;
      consoleErrors.push(t);
    }
  });
  page.on('pageerror', (err) => consoleErrors.push(String(err)));
  page.on('requestfailed', (req) => {
    const u = req.url();
    if (u.includes('favicon')) return;
    failedRequests.push(`${req.failure()?.errorText || 'failed'} ${u}`);
  });

  // Static + API preflight
  for (const path of [
    '/admin/',
    '/admin/ks/css/forge-fleet-admin.css',
    '/admin/ks/css/forge-theme.css',
    '/admin/ks/js/forge-theme.js',
    '/v1/version',
    '/v1/admin/snapshot',
  ]) {
    const res = await page.request.get(`${base}${path}`);
    if (!res.ok()) fail(`HTTP ${res.status()} ${path}`);
    else pass(`${path} → ${res.status()}`);
  }

  await page.goto(`${base}/admin/`, { waitUntil: 'domcontentloaded', timeout: 30000 });

  // Version line should populate
  try {
    await page.waitForFunction(
      () => {
        const el = document.getElementById('fleet-version-line');
        return el && !/Loading version/i.test(el.textContent || '');
      },
      { timeout: 25000 },
    );
    const ver = await page.locator('#fleet-version-line').textContent();
    pass(`version line: ${(ver || '').trim().slice(0, 80)}`);
  } catch {
    fail('fleet-version-line stayed on "Loading version…"');
  }

  // Tiles should render (not stuck on Loading tiles)
  try {
    await page.waitForFunction(
      () => {
        const el = document.getElementById('fleet-tiles');
        return el && !/^Loading tiles/i.test((el.textContent || '').trim());
      },
      { timeout: 30000 },
    );
    pass('overview tiles rendered');
  } catch {
    fail('#fleet-tiles stuck on "Loading tiles…"');
  }

  // No auth error banner on loopback
  const errVisible = await page.locator('#err').evaluate((el) => !el.classList.contains('d-none') && (el.textContent || '').trim().length > 0);
  if (errVisible) {
    const errText = await page.locator('#err').textContent();
    fail(`error banner visible: ${(errText || '').trim().slice(0, 120)}`);
  } else {
    pass('no error banner');
  }

  // Main chart should have SVG content
  const chartHtml = await page.locator('#fleet-load-chart').innerHTML();
  if (!chartHtml.includes('<svg') && !chartHtml.includes('No workload')) {
    fail('#fleet-load-chart missing SVG after snapshot load');
  } else {
    pass('overview chart has content');
  }

  // Tab: Jobs
  await page.click('#fleet-tab-jobs-btn');
  await page.waitForTimeout(400);
  const jobsPane = await page.locator('#fleet-tab-jobs').getAttribute('class');
  if (!jobsPane || !jobsPane.includes('show')) fail('Jobs tab did not activate');
  else pass('Jobs tab activates');

  // Tab: Apps
  await page.click('#fleet-tab-apps-btn');
  await page.waitForTimeout(400);
  const appsPane = await page.locator('#fleet-tab-apps').getAttribute('class');
  if (!appsPane || !appsPane.includes('show')) fail('Apps tab did not activate');
  else pass('Apps tab activates');

  // Telemetry history modal
  await page.click('#fleet-tab-overview-btn');
  await page.waitForTimeout(300);
  await page.click('#fleet-load-chart', { force: true });
  try {
    await page.waitForSelector('#fleet-tel-history-modal.show', { timeout: 8000 });
  } catch {
    /* bootstrap may set display without .show in some builds */
  }
  const modalOpen = await page.locator('#fleet-tel-history-modal').evaluate(
    (el) => el.classList.contains('show') || getComputedStyle(el).display === 'block',
  );
  if (!modalOpen) fail('telemetry history modal did not open on chart click');
  else pass('telemetry modal opened');

  try {
    await page.waitForFunction(
      () => {
        const st = document.getElementById('fleet-tel-hist-status');
        return st && !/^Loading/i.test((st.textContent || '').trim()) && !/Could not load/i.test(st.textContent || '');
      },
      { timeout: 60000 },
    );
    const status = await page.locator('#fleet-tel-hist-status').textContent();
    pass(`telemetry status: ${(status || '').trim().slice(0, 100)}`);
  } catch {
    const status = await page.locator('#fleet-tel-hist-status').textContent();
    fail(`telemetry modal load failed: ${(status || '').trim()}`);
  }

  for (const id of ['fleet-tel-chart-24h', 'fleet-tel-chart-7d', 'fleet-tel-chart-1mo', 'fleet-tel-chart-1y']) {
    const html = await page.locator(`#${id}`).innerHTML();
    if (!html.includes('<svg')) fail(`#${id} missing chart SVG`);
    else pass(`#${id} rendered`);
  }

  // buckets API from page context
  const bucketsProbe = await page.evaluate(async (origin) => {
    const r = await fetch(`${origin}/v1/telemetry?period=last_24_hours&format=buckets`, {
      headers: { Accept: 'application/json' },
    });
    const j = await r.json();
    return { ok: j.ok, format: j.format, count: j.count, buckets: Array.isArray(j.buckets) };
  }, base);
  if (!bucketsProbe.ok || bucketsProbe.format !== 'buckets' || !bucketsProbe.buckets) {
    fail(`buckets API from browser: ${JSON.stringify(bucketsProbe)}`);
  } else {
    pass(`buckets API: ${bucketsProbe.count} rows`);
  }

  if (failedRequests.length) {
    for (const fr of failedRequests.slice(0, 8)) fail(`request failed: ${fr}`);
  }

  if (consoleErrors.length) {
    for (const ce of [...new Set(consoleErrors)].slice(0, 8)) fail(`console error: ${ce.slice(0, 200)}`);
  } else {
    pass('no console errors');
  }

  await browser.close();

  console.log(`\nSmoke summary: ${issues.length} issue(s)`);
  if (issues.length) {
    process.exit(1);
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(2);
});
