# FH30 — PDCA handoff Postgres connection factory

**Program:** ff-granite-hosting-pdca · **Wave:** GW-3 · **Executor:** Composer 2.5  
**Requirements:** R03

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-market/` (sub-program FMH01)

**Denylist:** `.cursor/plans/*.plan.md`, Granite SSH deploy/data commands, forge-fleet runtime code

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `feat(fm-postgres): FMH01 connection factory` (forge-market); coordinator docs-only in forge-fleet

## Plan

Kick off GW-3: sub-program **FMH01** ships `db/connection.py` and wires `studio_server.get_db()`; SQLite remains default when DSN unset. Coordinator FH30 gate green when FMH01 gate passes (R03).

## Do

1. Execute `/home/lzvyahin/Code/forge-market/docs/prompts/fm-postgres-hosting-pdca/FMH01-connection-factory.md`.
2. Create `src/forge_market/db/connection.py` with `get_market_connection()` and `init_market_db()`.
3. Replace hardcoded `DB_PATH` in `studio_server/studio_server.py`.
4. Confirm SQLite default path still works when `FORGE_MARKET_DATABASE_URL` unset.

## Handoff

Sub-program: `forge-market/docs/prompts/fm-postgres-hosting-pdca/FMH01-connection-factory.md` ↔ coordinator **FH30**. Unblocks **FH31** / FMH02.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH30
cd /home/lzvyahin/Code/forge-market
./scripts/fm-postgres-hosting-pdca/check-phase-gate.sh FMH01
pytest tests/test_postgres_connection.py -k sqlite -q
```

## Act

Remediate until FH30 and FMH01 gates green; proceed to FH31.
