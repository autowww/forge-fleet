# FH35 — Secondary stores ADR (FMH06)

**Program:** ff-granite-hosting-pdca · **Wave:** GW-3 · **Executor:** Composer 2.5  
**Requirements:** R14

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-market/` (sub-program FMH06), `deploy/forge-market-studio/compose.yaml` (volume name alignment)

**Denylist:** `.cursor/plans/*.plan.md`, Granite SSH volume surgery

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `docs(fm-postgres): FMH06 secondary stores ADR` (forge-market)

## Plan

**FMH06** documents v1 strategy: `broker.db` and wiki workspaces stay on named volumes; only market core migrates to Postgres (R14).

## Do

1. Execute `/home/lzvyahin/Code/forge-market/docs/prompts/fm-postgres-hosting-pdca/FMH06-secondary-stores-adr.md`.
2. Create `docs/design/secondary-stores-adr.md`.
3. Align volume names with `forge-fleet/deploy/forge-market-studio/compose.yaml`.

## Handoff

Sub-program **FMH06** ↔ coordinator **FH35**. Unblocks **FH36** / FMH07.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH35
grep -q broker deploy/forge-market-studio/compose.yaml
cd /home/lzvyahin/Code/forge-market
./scripts/fm-postgres-hosting-pdca/check-phase-gate.sh FMH06
```

## Act

Remediate until FH35 and FMH06 gates green; proceed to FH36.
