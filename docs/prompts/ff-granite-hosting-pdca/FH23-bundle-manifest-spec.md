# FH23 — Bundle manifest spec

**Program:** ff-granite-hosting-pdca · **Wave:** GW-2 · **Executor:** Composer 2.5

## Plan

`.forge_migration_manifest.json` parsing with `corpus`, `raw_sec`, `broker`, `wiki` flags; step skip rules in `fleet_server/migrations.py`.

## Check

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH23
pytest tests/test_migrations_api.py -k manifest
```
