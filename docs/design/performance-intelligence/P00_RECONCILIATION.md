# P00 — Fleet Performance Intelligence reconciliation

Date: 2026-11-04. Source: Cursor handoff bundle `fleet_performance_intelligence_cursor_handoff_20261104`.

## Capability matrix (existing → target)

| Area | Today | Target |
| --- | --- | --- |
| Cluster story | Additive index on Benchmarks answer cards; reference fixed to **local** peer | Hero **modeled cluster capacity** with selectable baseline, trust-first headline (confirmed nodes), optional saved-snapshot view |
| Per-stage score | Implicit in composite via `composite_parts()` | Explicit **stage index** = 100 × T/R; cluster stage index = sum of included nodes |
| Weights | Fixed `COMPOSITE_WEIGHTS` in `fmsbench_runs.py` | User-adjustable weights (normalized), preset default 22/28/10/12/28 |
| Baseline | Always `reference_peer_id: local` | Data-driven baseline row; Granite only when 5 standard stages measured |
| Speedup / efficiency | Stage grid shows 1-thread vs max; UI says "threads" | **Worker speedup** and **worker efficiency** when `max_workers` known; oversubscription flagged |
| Insights | None | Deterministic rules (Observation / Meaning / Action) |
| UI IA | Single scroll: answers, workload bars, node table, runs, stage grid | Tabs: Overview, Workloads, Scoring, Nodes, Evidence & runs |
| API | `GET /v1/mesh/benchmarks` only | Add `GET /v1/mesh/benchmarks/score` view model; keep comparison payload for Capacity tab |
| Distributed throughput | Labelled "not verified" in copy | `verified_distributed_efficiency: null` explicit in API and UI |

## Real paths (verified)

| Layer | Path |
| --- | --- |
| Admin shell | `fleet_server/static/admin.html` — `#fleet-tab-benchmarks` |
| Benchmark render | `fleet_server/static/benchmarks-view.js` → replaced by `performance-view.js` (P03) |
| Load + run wiring | `fleet_server/static/capacity.js` — `loadCompare()`, rerun button handlers |
| Comparison API | `fleet_server/main.py` — `GET /v1/mesh/benchmarks` → `fmsbench_runs.comparison()` |
| Scoring today | `fleet_server/fmsbench_runs.py` — `composite_parts`, `cluster_total`, `stage_breakdown` |
| Runner | `fleet_server/fmsbench_bundle/bench_v2.py`, `execute_run`, `start_batch` |
| Fleet mark | `etc/host-profile.json` — `benchmark` only (no FMSBench) |
| Market Studio result | `etc/fmsbench-result.json`, `fmsbench-suite/results/`, `etc/forge-benchmarks/reports/` |
| Mesh snapshots | `etc/forge-benchmarks/mesh-snapshot.json` — `from_saved`, `live_error` |
| History | `etc/forge-benchmarks/market-studio.jsonl`, `hardware.jsonl` |
| Routes | `fleet_server/route_registry.py` — `read:profile` for benchmarks GET |
| Tests | `tests/test_fmsbench_separation.py`, `tests/test_admin_html_smoke.py` |

## Workers vs threads (do not relabel in data)

FMSBench scale keys in stored JSON are **benchmark worker counts** (`ThreadPoolExecutor` / `ProcessPoolExecutor` width). CLI `--threads` is intra-query engine parallelism (PostgreSQL `max_parallel_workers_per_gather`, etc.). The admin stage grid labels the widest scale as "threads" in places; Performance Intelligence UI will say **workers** when the value comes from `multi.threads` in `stage_breakdown`. Mercury **8 workers / 4 logical CPUs** is preserved as recorded metadata plus `WORKER_OVERSUBSCRIPTION` insight — not auto-corrected to 4.

## Granite baseline

No committed fixture in-repo proves Granite has five comparable **standard** profile max-worker rates. Baseline selection is runtime: any peer row with complete standard stages becomes eligible. Until Granite qualifies, default baseline remains **local** (or first eligible row) with status `temporary_fallback` when handoff Precision=100 semantics apply to operator data.

## Data gaps

| Gap | Mitigation |
| --- | --- |
| No unified `fixture_hash` on every row | Adapter uses `summary.workload_checksum` + `data_revision` when present; else profile + suite_version |
| Saved peer with `http_401` | `saved_snapshot` + `connectivity`; trust-first excludes from hero unless toggle |
| Unknown `max_workers` (e.g. transcribed ASUS) | Speedup from rates; `worker_efficiency: null` |
| Non-standard profile on displayed result | Mark **incompatible** for apples-to-apples score |
| Partial NLP on reference | Existing NLP renormalization in `composite_parts`; domain will mirror with explicit flags |

## Phased plan

P01 domain → P02 adapter/API → P03 UI → P04 insights → P05 verify/docs/ship.

## Test commands

```bash
cd /home/lzvyahin/Code/forge-fleet
pytest tests/test_fmsbench_separation.py -q
pytest tests/test_perf_scoring.py -q          # after P01
pytest tests/test_perf_insights.py -q         # after P04
pytest tests/test_perf_score_api.py -q        # after P02
pytest tests/test_admin_html_smoke.py -q      # after P03
```

Oracle (handoff bundle): `python -m unittest discover -s scoring -v` from extracted handoff root.

## Classification ledger

| ID | Class | Item |
| --- | --- | --- |
| B1 | EXIT BLOCKER | None for P00 (recon only) |
| B2 | EXIT BLOCKER (P05) | Oracle golden values must match domain tests |
| H1 | HARDENING | Handbook submodule bump / Firebase deploy (operator-triggered) |
| H2 | HARDENING | `scripts/smoke-admin-ui.mjs` full browser smoke |
| L1 | BACKLOG | Verified distributed efficiency measurement (out of scope) |
| L2 | BACKLOG | LLM-generated insights |
| L3 | LIMITATION | `update-fleet.sh` requires stashing unrelated `deploy/open-webui/bridge` dirty tree before ship |

## Acceptance distance (start of program)

0 of 17 mandatory functional criteria in `ACCEPTANCE_AND_ROLLOUT.md` — baseline P00 complete when this file is merged.
