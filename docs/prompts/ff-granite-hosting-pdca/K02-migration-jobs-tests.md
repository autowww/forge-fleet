# K02 — Migration jobs tests and docs

**Program:** ff-granite-hosting-pdca · **Wave:** K · **Executor:** Composer 2.5

Read [00-master-sequence.md](00-master-sequence.md). Prior **K01** gate must be green before starting.

## Agent isolation

**Allowlist:** `fleet_server/migration_jobs.py`, `fleet_server/migration_stubs/`, `tests/`, `docs/build-201/09-migration-api.md`

**Denylist:** `forge-migrator/`, `.cursor/plans/*.plan.md`, unrelated repos

## Plan

Tests assert `migrate_db` job argv contains `migrate_sqlite_to_postgres.py` path and `--all`. Docs note real migrate tool replaces prior stub.

## Do

1. Add or extend unit tests for migration job argv (grep `migrate_sqlite_to_postgres.py`, `--all`).
2. Negative: assert Alpine echo-only stub is not the sole migrate command.
3. Finalize `docs/build-201/09-migration-api.md` migrate_db section for operators.

## Check

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh K02
pytest tests/ -k migration -q
```

## Adjust

Remediate until gate is green.
