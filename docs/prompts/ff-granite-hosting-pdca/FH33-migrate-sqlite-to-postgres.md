# FH33 — migrate sqlite to postgres tool (FMH04)

**Program:** ff-granite-hosting-pdca · **Wave:** GW-3 · **Executor:** Composer 2.5  
**Requirements:** R03, R05

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-market/`, `fleet_server/migration_jobs.py` (argv alignment only)

**Denylist:** `.cursor/plans/*.plan.md`, Granite SSH data transfer, manual `scp`/`rsync`

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `feat(fm-postgres): FMH04 migrate sqlite to postgres tool` (forge-market)

## Plan

**FMH04** ships `tools/migrate_sqlite_to_postgres.py`; Fleet FH26 `migrate_db` job argv references this tool (R03, R05).

## Do

1. Execute `/home/lzvyahin/Code/forge-market/docs/prompts/fm-postgres-hosting-pdca/FMH04-migrate-sqlite-to-postgres.md`.
2. Create `tools/migrate_sqlite_to_postgres.py` with upsert + row count output.
3. Align Fleet `migrate_db` step template in `fleet_server/migration_jobs.py` if argv drifted.

## Handoff

Sub-program **FMH04** ↔ coordinator **FH33**. Unblocks Fleet migration job e2e and **FH34** / FMH05.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH33
cd /home/lzvyahin/Code/forge-market
./scripts/fm-postgres-hosting-pdca/check-phase-gate.sh FMH04
pytest tests/test_migrate_sqlite_to_postgres.py -q
```

## Act

Remediate until FH33 and FMH04 gates green; proceed to FH34.
