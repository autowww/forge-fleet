# FH36 — Postgres tests (FMH07)

**Program:** ff-granite-hosting-pdca · **Wave:** GW-3 · **Executor:** Composer 2.5  
**Requirements:** R03, R15

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-market/` (sub-program FMH07)

**Denylist:** `.cursor/plans/*.plan.md`, Granite SSH deploy/data commands

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `test(fm-postgres): FMH07 postgres tests` (forge-market)

## Plan

**FMH07** adds `pytest -k postgres` coverage and container bearer smoke; live Postgres tests skip when DSN unset (R03, R15 partial).

## Do

1. Execute `/home/lzvyahin/Code/forge-market/docs/prompts/fm-postgres-hosting-pdca/FMH07-postgres-tests.md`.
2. Add `tests/test_postgres_connection.py` and `tests/test_migrate_sqlite_to_postgres.py`.
3. Add `psycopg[binary]` to studio-server requirements.

## Handoff

Sub-program **FMH07** ↔ coordinator **FH36**. Unblocks **FH37** / FMH08.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH36
cd /home/lzvyahin/Code/forge-market
./scripts/fm-postgres-hosting-pdca/check-phase-gate.sh FMH07
pytest tests/ -k postgres -q
```

## Act

Remediate until FH36 and FMH07 gates green; proceed to FH37.
