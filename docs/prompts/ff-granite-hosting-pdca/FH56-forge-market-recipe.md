# FH56 — forge-market recipe (FMI07)

**Program:** ff-granite-hosting-pdca · **Wave:** GW-5 · **Executor:** Composer 2.5  
**Requirements:** R07, R08

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-migrator/` (sub-program FMI07)

**Denylist:** `.cursor/plans/*.plan.md`, Granite SSH deploy/data ops in recipe steps

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `feat(fmigr): FMI07 forge-market recipe` (forge-migrator)

## Plan

**FMI07** ships full `recipes/forge-market.yaml`: local inventory → Fleet upload → verify → rollback drill (R07, R08).

## Do

1. Execute `/home/lzvyahin/Code/forge-migrator/docs/prompts/fmigr-wizard-pdca/FMI07-forge-market-recipe.md`.
2. Align recipe steps with Fleet migration jobs (FH20–FH28).
3. Include AI modernization step tagged for Cursor agent panel.

## Handoff

Sub-program **FMI07** ↔ coordinator **FH56**. Unblocks **FH57** / FMI08.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH56
cd /home/lzvyahin/Code/forge-migrator
./scripts/fmigr-wizard-pdca/check-phase-gate.sh FMI07
test -f recipes/forge-market.yaml
```

## Act

Remediate until FH56 and FMI07 gates green; proceed to FH57.
