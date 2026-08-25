# K01 — Fleet migrate_db job argv

**Program:** ff-granite-hosting-pdca · **Wave:** K · **Executor:** Composer 2.5

Read [00-master-sequence.md](00-master-sequence.md) and coordinator [FH33-migrate-sqlite-to-postgres.md](FH33-migrate-sqlite-to-postgres.md). Prior fm-postgres **H02** gate must be green before starting.

## Agent isolation

**Allowlist:** `fleet_server/migration_stubs/migrate_db.sh`, `fleet_server/migration_jobs.py`, `tests/`, `docs/build-201/09-migration-api.md`

**Denylist:** `forge-migrator/`, `.cursor/plans/*.plan.md`, unrelated repos

## Plan

Refresh FH26/FH33: `migrate_db` step runs `docker run` **forge-market-app** image with `python tools/migrate_sqlite_to_postgres.py --all`, bundle mount, `FORGE_MARKET_DATABASE_URL` pointing at compose Postgres — not Alpine echo stub.

## Do

1. Update `fleet_server/migration_stubs/migrate_db.sh` to invoke market migrate tool `--all` inside app image.
2. Wire `fleet_server/migration_jobs.py` argv: bundle mount path, DSN env to Postgres sidecar.
3. Document stub→real transition in `docs/build-201/09-migration-api.md`.

## Check

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh K01
```

Gate greps migrate tool path in argv/stub; not bare echo stub.

## Adjust

Remediate until gate is green.
