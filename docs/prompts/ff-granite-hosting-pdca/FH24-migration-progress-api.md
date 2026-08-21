# FH24 — Migration progress API

**Program:** ff-granite-hosting-pdca · **Wave:** GW-2 · **Executor:** Composer 2.5

## Plan

`GET /v1/migrations/{id}` returns step states, bundle byte totals, and `bytes_transferred`.

## Check

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH24
pytest tests/test_migrations_api.py -k bytes
```
