# P06 — Prototype fidelity (Benchmarks studio)

Date: 2026-11-04.

## Goal

Match the handoff clickable prototype (`fleet_performance_intelligence_v2.html`) inside the Fleet admin Benchmarks tab: light `.fpi` studio island, navy hero, left rail with five pages, KPI strip, component cards, scaling matrix, Decision signals, full insight cards, workload explorer, scoring anatomy, node provenance.

## Delivered

- [`fleet_server/static/performance-view.css`](../../fleet_server/static/performance-view.css) — prototype styles scoped under `.fpi` with `html[data-bs-theme="dark"] .fpi` token overrides.
- [`fleet_server/static/performance-view.js`](../../fleet_server/static/performance-view.js) — single-root renderer with rail router; data from `GET /v1/mesh/benchmarks/score` unchanged.
- [`fleet_server/static/admin.html`](../../fleet_server/static/admin.html) — `#fleet-perf-studio` shell; run controls remain in `#fleet-perf-evidence-static` (moved into Evidence page on render).

## Deliberate deviations

| Prototype | Fleet |
| --- | --- |
| Manual “Set Granite baseline” modal | Granite baseline from live standard runs only |
| Demo literals (ASUS/Venus/Mercury names) | Live peer labels and evidence from adapter |
| Standalone full-page app | Nested under Fleet admin shell + scope selector |
| Light-only CSS file | Dark admin theme gets tuned `.fpi` dark tokens |

## Evidence

- `evidence/benchmarks-desktop.png` — Command center
- `evidence/benchmarks-insights.png` — Insights & actions rail page
- `evidence/benchmarks-narrow.png` — responsive rail collapse

## Verify

```
pytest tests/test_admin_html_smoke.py::test_admin_benchmarks_performance_shell tests/test_perf_score_api.py -q
node --check fleet_server/static/performance-view.js
node scripts/smoke-admin-ui.mjs --base http://127.0.0.1:18766
```
