# FH28 — GW-2 wave closeout

**Program:** ff-granite-hosting-pdca · **Wave:** GW-2 · **Executor:** Composer 2.5

## Plan

`docs/build-201/09-migration-api.md` runbook; migration API tests green; GW-2 gate checks deliverables (R17 partial — handbook OpenAPI in FH70).

## Check

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH28
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh GW-2
pytest tests/test_migrations_api.py
```
