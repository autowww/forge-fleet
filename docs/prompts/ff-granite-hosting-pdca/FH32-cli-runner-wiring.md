# FH32 — CLI runner wiring (FMH03)

**Program:** ff-granite-hosting-pdca · **Wave:** GW-3 · **Executor:** Composer 2.5  
**Requirements:** R03

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-market/` (sub-program FMH03)

**Denylist:** `.cursor/plans/*.plan.md`, Granite SSH deploy/data commands

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `feat(fm-postgres): FMH03 CLI runner wiring` (forge-market)

## Plan

**FMH03** routes CLI tools and schedulers through `init_market_db()` / `get_market_connection()` instead of hardcoded SQLite paths (R03).

## Do

1. Execute `/home/lzvyahin/Code/forge-market/docs/prompts/fm-postgres-hosting-pdca/FMH03-cli-runner-wiring.md`.
2. Audit `tools/run_*.py` and scheduler scripts for direct `sqlite3.connect("data/market.db")`.
3. Keep SQLite default when DSN unset.

## Handoff

Sub-program **FMH03** ↔ coordinator **FH32**. Unblocks **FH33** / FMH04.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH32
cd /home/lzvyahin/Code/forge-market
./scripts/fm-postgres-hosting-pdca/check-phase-gate.sh FMH03
```

## Act

Remediate until FH32 and FMH03 gates green; proceed to FH33.
