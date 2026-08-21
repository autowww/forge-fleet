# FH31 — Postgres DDL (FMH02)

**Program:** ff-granite-hosting-pdca · **Wave:** GW-3 · **Executor:** Composer 2.5  
**Requirements:** R03

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-market/` (sub-program FMH02)

**Denylist:** `.cursor/plans/*.plan.md`, Granite SSH deploy/data commands

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `feat(fm-postgres): FMH02 postgres DDL` (forge-market)

## Plan

**FMH02** ports core `_SCHEMA` tables to Postgres via `PostgresStoreAdapter.ensure_schema()`; design doc updated (R03).

## Do

1. Execute `/home/lzvyahin/Code/forge-market/docs/prompts/fm-postgres-hosting-pdca/FMH02-postgres-ddl.md`.
2. Extend `src/forge_market/db/postgres.py` with `ensure_schema()`.
3. Document tables in `docs/design/postgres-production-store.md`.

## Handoff

Sub-program **FMH02** ↔ coordinator **FH31**. Unblocks **FH32** / FMH03.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH31
cd /home/lzvyahin/Code/forge-market
./scripts/fm-postgres-hosting-pdca/check-phase-gate.sh FMH02
```

## Act

Remediate until FH31 and FMH02 gates green; proceed to FH32.
