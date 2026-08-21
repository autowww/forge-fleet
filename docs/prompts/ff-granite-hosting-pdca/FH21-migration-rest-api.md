# FH21 — Migration REST API

**Program:** ff-granite-hosting-pdca · **Wave:** GW-2 · **Executor:** Composer 2.5

## Plan

`POST /v1/migrations` and `GET /v1/migrations/{id}` wired in `fleet_server/main.py`.

## Check

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH21
pytest tests/test_migrations_api.py -k post_get
```
