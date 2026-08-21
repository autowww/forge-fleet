# FH20 — Migration store schema

**Program:** ff-granite-hosting-pdca · **Wave:** GW-2 · **Executor:** Composer 2.5

## Plan

SQLite `migrations` + `migration_steps` tables and CRUD helpers in `fleet_server/store.py`; schema version bump; `fleet_server/migrations.py` module scaffold.

## Agent isolation

**Allowlist:** `fleet_server/`, `tests/`, `docs/build-201/`, `docs/prompts/ff-granite-hosting-pdca/`, `scripts/ff-granite-hosting-pdca/`

## Check

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH20
```
