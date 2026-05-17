# Fleet documentation — enterprise readiness scorecard (post-refactor)

**Date:** 2026-05-17  
**Repository:** forge-fleet (commit: run `git rev-parse HEAD`)  
**Scope:** Handbook source in **`docs/`**, OpenAPI in **`docs/schemas/openapi.json`**, CI **`docs-contracts.yml`**.

## Automated checks (evidence)

Run locally: **`bash scripts/check-docs-all.sh`** and **`python3 -m pytest -q tests`**.

| Check | Expected |
| --- | --- |
| **`check-docs-contracts.py`** | **PASS** — 43 routes |
| **`check-docs-links.py`** | **PASS** — broad link coverage |
| **`check-docs-examples.py`** | **PASS** |
| **`check-docs-public-copy.py`** | **PASS** |
| **`check-openapi-quality.py`** | **PASS** |
| **`check-schema-examples.py`** | **PASS** (with **`.[docs]`**) |
| **`check-version-consistency.py`** | **PASS** |
| **`pytest`** | **PASS** |

## Scores (0–10, evidence-based snapshot)

| Area | Score | Notes |
| --- | ---: | --- |
| IA / navigation | 8 | Start → Learn → Build → Operate → Reference → Examples tables landed |
| Homepage / product story | 8 | README + Start hub explain roles + 5-minute check |
| Learn 101 | 8 | Tutorials + first job fixed for **201** + **`kind`** |
| Build 201 | 8 | Integration index + practitioner README pattern |
| Operate 301 | 8 | Threat model, runbook rows, backup / SLO / checklist pages |
| API reference | 8 | Tables + OpenAPI alignment note |
| OpenAPI contract | 7 | **`operationId`**, path params, job body/201; deeper response schemas still incremental |
| JSON Schema | 7 | Payload validator; per-schema prose enrichment still incremental |
| Examples | 8 | Canonical JSON + multi-language **`kind`** fixes |
| KS visuals | 8 | `blueprint-diagram-ascii` coverage map updated |
| Docs CI | 9 | Aggregated **`check-docs-all.sh`** + pytest in workflow |
| Website deployment | 7 | Static smoke + live **`check-live-docs-site.sh`**; depends on submodule bump cadence |
| Version trust | 8 | Changelog **0.3.61** + consistency script |

**Band:** ~**82–88** — strong public handbook candidate; remaining gap is **deeper OpenAPI response components** and **continuous live deploy verification** in CI (networked job).

## Release recommendation

**Ship / refresh handbook** for **`0.3.61`** with the understanding that **production Hosting** must pick up the **forge-fleet** submodule bump in **forge-fleet-website**.

## Non-blocking next PRs

1. Expand OpenAPI **`components.schemas`** for every major response type.  
2. Add more **`payloads/valid/*.json`** fixtures per schema.  
3. Optional CI job (cron) running **`check-live-docs-site.sh`** with secrets-free probes only.
