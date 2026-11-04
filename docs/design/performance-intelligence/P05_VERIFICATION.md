# P05 — Fleet Performance Intelligence verification

Date: 2026-11-04.

## Phase and completed features

| Phase | Status |
| --- | --- |
| P00 Reconciliation | Complete — `P00_RECONCILIATION.md` |
| P01 Scoring domain | Complete — `fleet_server/perf_scoring.py`, oracle parity tests |
| P02 Adapter + API | Complete — `GET /v1/mesh/benchmarks/score`, `evidence_from_rows` |
| P03 UI | Complete — `performance-view.js`, tabbed Benchmarks admin |
| P04 Insights | Complete — `fleet_server/perf_insights.py` |
| P05 Verify + docs | This report |

## Paths changed (high level)

- Domain: `fleet_server/perf_scoring.py`, `fleet_server/perf_insights.py`
- Integration: `fleet_server/fmsbench_runs.py`, `fleet_server/main.py`, `fleet_server/route_registry.py`
- UI: `fleet_server/static/performance-view.js`, `admin.html`, `capacity.js`
- Tests: `tests/test_perf_*.py`, `tests/fixtures/perf_screenshot_fixture.json`
- Docs: `docs/design/performance-intelligence/*`, `docs/learn-101/11-forge-benchmarks.md`, `docs/reference/01-http-api-reference.md`, `docs/schemas/openapi.json`

## New data fields / migrations

No DB migrations. Scoring read model is computed from existing `fmsbench-result.json`, host profile, and mesh snapshot JSON. Client policy (baseline, weights, include_snapshots) stored in `localStorage` only.

## Baseline and evidence

- Default baseline: local peer when eligible; Granite selectable only when five standard max-worker stages exist on that row.
- Trust-first headline: `cluster.composite` = `composite_confirmed` unless `include_snapshots=1`.
- Handoff fixture oracle values verified in `tests/test_perf_scoring.py` (Precision 100, cluster 177.511 / 135.009 without snapshots).

## Scoring fixture test results

```
pytest tests/test_perf_scoring.py tests/test_perf_insights.py tests/test_perf_score_api.py tests/test_fmsbench_separation.py tests/test_admin_html_smoke.py -q
```

Handoff bundle oracle (independent):

```
python -m unittest discover -s /tmp/fpi-handoff/fleet_performance_intelligence_cursor_handoff_20261104/scoring -v
```

## Interaction / browser smoke

- Admin shell smoke: `tests/test_admin_html_smoke.py` (includes `fleet-perf-tablist`, run button IDs).
- Full `scripts/smoke-admin-ui.mjs`: run locally when Fleet admin is up on port 18766.
- Desktop/narrow screenshots: capture `/admin/#benchmarks` after `update-user.sh` (not committed in this pass — BACKLOG H2).

## Acceptance criteria (mandatory)

| Criterion | Status |
| --- | --- |
| Modeled cluster + worker scaling main story | PASS (Overview hero + speedup matrix) |
| Baseline visible with provenance | PASS (hero + Scoring tab) |
| Per-node 5 indexes + composite + speedup | PASS (Nodes + API) |
| Per-workload cluster index + weight + contribution | PASS (Overview components) |
| Oracle fixture arithmetic | PASS (unit tests) |
| Contributions sum to cluster | PASS (invariant tests) |
| Snapshot toggle 177.5 → 135.0 | PASS (API + UI checkbox) |
| Venus not measured (not zero) | PASS |
| Mercury 8 workers / 4 CPUs flagged | PASS (insight + oversubscription flag) |
| ASUS unknown workers → no false efficiency | PASS |
| Hardware mark separate from composite | PASS |
| Incompatible profile excluded | PASS (adapter + insight) |
| Insight observation/meaning/action | PASS |
| Rerun controls preserved | PASS (same button IDs in Evidence tab) |
| Distributed efficiency not measured | PASS (`verified_distributed_efficiency: null` + insight) |

**Distance to full acceptance:** 17 / 17 functional criteria met in code/tests; browser screenshots and full UI automation remain HARDENING (H2).

## Open issues

| Class | Item |
| --- | --- |
| HARDENING | Playwright/desktop+narrow screenshots in `docs/design/performance-intelligence/evidence/` |
| HARDENING | Handbook submodule rebuild/deploy (`forge-fleet-website`) on operator request |
| BACKLOG | Verified distributed throughput measurement |
| LIMITATION | Granite baseline until live five-stage standard runs exist on Granite peer |

## Rollback

Revert commits `1874bdf` … `P05 commit` on `forge-fleet` master, or install previous apt package from packages CDN.
