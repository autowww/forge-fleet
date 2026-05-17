# Maintainers — Handbook contracts and CI

> **Maintainer-facing:** contract scripts describe **HTTP surface area** and **handbook hygiene**, not user journeys. Run **`bash scripts/check-docs-all.sh`** before publishing schema-heavy changes.

## Primary checks (forge-fleet repo root)

| Script | Role |
| --- | --- |
| **`check-docs-contracts.py`** | Every **`fleet_server/main.py`** route appears in **`docs/schemas/openapi.json`** |
| **`check-docs-json.py`** | All documented JSON files parse |
| **`check-docs-links.py`** | Relative links resolve (**`.md`**, **`.json`**, **`.py`**, images, dirs) |
| **`check-docs-examples.py`** | Public **`POST /v1/jobs`** snippets include **`kind: docker_argv`** |
| **`check-docs-public-copy.py`** | Forbidden scaffold words stay out of public docs |
| **`check-openapi-quality.py`** | **`operationId`**, path params, **`POST /v1/jobs`** body + 201 response |
| **`check-schema-examples.py`** | Payloads under **`docs/examples/payloads/valid/`** validate (**requires** **`pip install -e '.[docs]'`**) |
| **`check-docs-assets.py`** | Local image paths exist |
| **`check-version-consistency.py`** | **`pyproject.toml`**, OpenAPI **`info.version`**, changelog head |
| **`apply_openapi_contract.py`** | (Regenerate) add stable OpenAPI metadata — run after large route edits |

**Aggregate:** **`bash scripts/check-docs-all.sh`**

## CI

**`.github/workflows/docs-contracts.yml`** installs **`pip install -e ".[docs]"`** then runs **`check-docs-all.sh`** plus **`pytest`**.

## Static site mirror (forge-fleet-website)

After bumping the **forge-fleet** submodule:

```bash
cd ../forge-fleet-website
python3 generator/build-site.py
python3 scripts/check-site-smoke.py
python3 scripts/check-site-ux.py
```

**IA:** when you add a new **top-level** handbook section, extend **`docs/site-nav.yaml`** in **forge-fleet** so horizontal nav and section sidebars stay manifest-driven.

See **[DOCS-DEPLOYMENT-VERIFICATION.md](DOCS-DEPLOYMENT-VERIFICATION.md)** for live URL smoke tests.

False positives in link or copy checks should be rare; document suppressions in PR text—avoid silent `<!-- docs:skip-...-->` except for fenced blocks already called out in **`EXAMPLES-VALIDATION.md`**.

Use **[DOCS-RELEASE-CHECKLIST.md](DOCS-RELEASE-CHECKLIST.md)** before handbook publishes even when CI is green locally.
