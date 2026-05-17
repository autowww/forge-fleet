# Fleet docs gap scorecard (baseline)

This file was produced per **Prompt 01 — Rebaseline audit**. Re-run the inventory and checks before major releases; refresh scores after each workstream.

## Run metadata

| Field | Value |
| --- | --- |
| Timestamp (UTC) | 2026-05-17 |
| Repository | forge-fleet |
| Commit | `0386d218a62512239901942d4a82689650abe4f6` |

## Live site verification

| Check | Result |
| --- | --- |
| `GET https://fleet.forgesdlc.com/` | **200** — Forge Fleet handbook HTML served |
| `GET https://fleet.forgesdlc.com/examples.html` (or equivalent nav target) | **200** — examples reachable from deployed nav |
| `GET https://fleet.forgesdlc.com/schemas/openapi.json` | **200** |
| Guessed `/docs-learn-101.html` / `/docs-start.html` on prod | **404** — live URL shape may differ from local `forge-fleet-website/website/` filenames; treat **IA parity as unverified** until probed from current homepage links |

**Conclusion:** Production serves handbook home + OpenAPI JSON; **do not assume** local handbook filenames match production without fetching the live nav. Source readiness and deployed URL contract should be re-checked after each deploy (see Prompt 15).

## Commands (local)

| Command | Result (baseline) |
| --- | --- |
| `python3 scripts/check-docs-json.py` | OK |
| `python3 scripts/check-docs-links.py` | OK (Markdown `.md` targets only) |
| `python3 scripts/check-docs-contracts.py` | OK (43 routes) |
| `python3 -m pytest -q tests` | **1 failed** — `test_resolve_argv_docker_respects_fleet_docker_bin` (override path not honored when file absent); **104 passed**, 1 skipped |

## Source inventory

| Kind | Count |
| --- | ---: |
| Files under `docs/` | 70 |
| Markdown under `docs/` | 53 |
| JSON under `docs/` | 16 |
| OpenAPI operations (unique method+path) | 43 |

## OpenAPI metrics (docs/schemas/openapi.json)

| Metric | Count |
| --- | ---: |
| Operations | 43 |
| With `operationId` | 0 |
| With `summary` or `description` | 43 (summary present on audited sample) |
| With `parameters` | 0 |
| With `requestBody` | 0 |
| Responses wired with JSON `schema` | 0 (baseline: generic text descriptions) |

## Example correctness (grep-level)

| Finding | Notes |
| --- | --- |
| `POST /v1-jobs` bodies missing `kind: docker_argv` | Present in **learn-101/06-first-fleet-job.md**, **examples/python.md**, **examples/ci-smoke.md**, **build-201/05-examples-and-recipes.md** (curl body) |
| First-job doc HTTP status | Table claims **HTTP 200** on create; **`fleet_server/main.py` returns 201** for successful `POST /v1/jobs` |
| Env naming | Mix of `FLEET_BEARER_TOKEN` vs prompt target `FLEET_TOKEN` / `FLEET_BASE_URL` |

## Link checker scope (baseline)

- `scripts/check-docs-links.py` only validates **`.md`** href targets, not `.json`, `.py`, `.sh`, images, or directories — **gap vs Prompt 03**.

## Public copy scan (informal)

- Full forbidden-word scan not automated yet; **Prompt 03** adds `check-docs-public-copy.py`.

## Scores (0–10, baseline — subjective with evidence)

| Area | Score | Evidence |
| --- | ---: | --- |
| IA / navigation | 6 | Folder IA matches Start → 101 → 201 → 301 → Reference → Examples; live URL mapping uncertain |
| Human-facing product story | 5 | README handbook-oriented; needs role/path chooser (Prompt 04) |
| Learn 101 tutorials | 5 | Good files; first-job example/schema/status gaps |
| Build 201 guides | 6 | Substantive; needs task template polish + example split (Prompt 06) |
| Operate 301 enterprise | 5 | Solid start; missing dedicated backup/DR, SLO, deployment checklist pages (Prompt 07) |
| API reference (narrative) | 7 | `01-http-api-reference.md` useful |
| OpenAPI contract quality | 4 | Parity OK; no `operationId`, params, bodies, response schemas |
| JSON Schema quality | 5 | Files exist; light metadata vs Prompt 09 |
| Examples / recipes | 5 | Coverage good; correctness and validation gaps |
| Kitchen Sink visuals | 4 | Some assets; VISUAL-COVERAGE incomplete vs Prompt 11 |
| Docs CI / quality gates | 4 | JSON + shallow links + contracts only |
| Release / version trust | 4 | `pyproject` **0.3.61** vs changelog latest **0.3.54**; screenshot may be stale |
| Website deployment confidence | 5 | Live site up; handbook path contract needs scripted verification |

## Release blockers (baseline)

1. Job-create docs/examples must include `kind: docker_argv` and match **HTTP 201** (source truth).
2. OpenAPI not client-grade (`operationId`, parameters, request/response schemas).
3. Link and public-copy CI too shallow; examples not schema-validated in CI.
4. Tests: one failing unit (`FLEET_DOCKER_BIN` argv resolution expectation vs implementation).
5. Changelog / version story out of sync with package version.

## Suggested PR sequence

Align with **Prompt 17** / pack README: correctness hotfixes → full link + copy lint → IA → Learn 101 → Build 201 → Operate 301 → OpenAPI + schemas → examples library → KS visuals → website integration → CI aggregate → release/version trust → live smoke → final scorecard + rollout doc refresh.
