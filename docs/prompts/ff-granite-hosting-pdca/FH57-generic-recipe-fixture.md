# FH57 — Generic recipe fixture (FMI08)

**Program:** ff-granite-hosting-pdca · **Wave:** GW-5 · **Executor:** Composer 2.5  
**Requirements:** R07

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-migrator/` (sub-program FMI08)

**Denylist:** `.cursor/plans/*.plan.md`

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `feat(fmigr): FMI08 generic recipe fixture` (forge-migrator)

## Plan

**FMI08** adds `recipes/_example-minimal.yaml` proving engine is product-agnostic (R07).

## Do

1. Execute `/home/lzvyahin/Code/forge-migrator/docs/prompts/fmigr-wizard-pdca/FMI08-generic-recipe-fixture.md`.
2. Add minimal second recipe with no forge-market-specific steps.
3. Document recipe authoring in migrator README.

## Handoff

Sub-program **FMI08** ↔ coordinator **FH57**. Unblocks **FH58** / FMI09.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH57
cd /home/lzvyahin/Code/forge-migrator
./scripts/fmigr-wizard-pdca/check-phase-gate.sh FMI08
test -f recipes/_example-minimal.yaml
```

## Act

Remediate until FH57 and FMI08 gates green; proceed to FH58.
