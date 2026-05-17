# Fleet documentation — staged rollout / PR plan

Use this sequence when splitting reviews. Evidence of what landed lives in **[DOCS-ENTERPRISE-SCORECARD.md](DOCS-ENTERPRISE-SCORECARD.md)** and **`DOCS-GAP-SCORECARD.md`**.

| PR | Title (suggestion) | Scope | Key commands | Depends on |
| --- | --- | --- | --- | --- |
| 1 | Docs correctness — job examples | **`kind`**, **HTTP 201**, **`check-docs-examples.py`** | `check-docs-examples.py` | — |
| 2 | Link + copy CI | **`check-docs-links.py`**, **`check-docs-public-copy.py`**, workflow | `check-docs-links.py`, `check-docs-public-copy.py` | PR1 optional |
| 3 | IA / README / Start hub | README, **`docs/start/`**, section READMEs | `check-docs-all.sh` | PR2 |
| 4 | Learn 101 polish | Tutorial metadata, cross-links | `check-docs-examples.py` | PR1 |
| 5 | Build 201 + recipes | Integration index, guides | `check-docs-links.py` | PR3 |
| 6 | Operate 301 enterprise | Security tables, runbook rows, new DR/SLO/checklist pages | `check-links` | PR3 |
| 7 | OpenAPI contract pass | **`apply_openapi_contract.py`**, **`check-openapi-quality.py`** | both scripts + `check-docs-contracts.py` | PR2 |
| 8 | Schema payloads | **`payloads/valid/`**, **`check-schema-examples.py`**, optional **`[docs]`** extra | `check-schema-examples.py` | PR7 |
| 9 | KS diagrams | `blueprint-diagram-ascii` fences, **`VISUAL-COVERAGE.md`** | `check-docs-assets.py` | PR3 |
| 10 | Website + live smoke | **forge-fleet-website** submodule, **`check-site-smoke.py`**, **`check-live-docs-site.sh`** | site scripts | PR7 + content |
| 11 | Release trust | **`pytest`** config, **CHANGELOG**, **`check-version-consistency.py`** | `pytest`, version script | PR1–8 |

## Reviewer checklist (each PR)

- `bash scripts/check-docs-all.sh` (or scoped scripts named in PR).  
- No forbidden copy in public paths.  
- OpenAPI parity if routes touched.

## Rollback

Revert the PR; rerun **`install-update.sh` / `update-user.sh`** on hosts only if a broken **OpenAPI** or docs payload shipped to production schema consumers (rare).
