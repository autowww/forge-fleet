# FH27 — Job register edge route

**Program:** ff-granite-hosting-pdca · **Wave:** GW-2 · **Executor:** Composer 2.5

## Plan

`register_edge_route` and `deploy_service` / `build_image` step kinds invoke stub scripts via runner.

## Check

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH27
pytest tests/test_migrations_api.py -k step_run
```
