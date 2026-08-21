# FH22 — Data bundle upload

**Program:** ff-granite-hosting-pdca · **Wave:** GW-2 · **Executor:** Composer 2.5

## Plan

`PUT /v1/migrations/{id}/data-bundle`; `migration_bundle` profile in `workspace_bundle.WORKSPACE_PROFILES` (2 GiB uncompressed, 500 MiB upload via env).

## Check

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH22
pytest tests/test_migrations_api.py -k data_bundle
```
