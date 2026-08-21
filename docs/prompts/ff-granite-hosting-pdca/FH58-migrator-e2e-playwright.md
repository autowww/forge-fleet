# FH58 — Migrator e2e Playwright (FMI09)

**Program:** ff-granite-hosting-pdca · **Wave:** GW-5 · **Executor:** Composer 2.5  
**Requirements:** R09

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-migrator/` (sub-program FMI09)

**Denylist:** `.cursor/plans/*.plan.md`

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `test(fmigr): FMI09 migrator e2e playwright` (forge-migrator)

## Plan

**FMI09** Playwright spec drives wizard against live migrator server (mock Fleet acceptable) (R09).

## Do

1. Execute `/home/lzvyahin/Code/forge-migrator/docs/prompts/fmigr-wizard-pdca/FMI09-migrator-e2e-playwright.md`.
2. Add Playwright spec covering recipe run + progress UI.
3. Wire `npm run test:e2e` in migrator UI package.

## Handoff

Sub-program **FMI09** ↔ coordinator **FH58**. Unblocks **FH59** GW-5 closeout.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH58
cd /home/lzvyahin/Code/forge-migrator
./scripts/fmigr-wizard-pdca/check-phase-gate.sh FMI09
cd migrator-ui && npm run test:e2e
```

## Act

Remediate until FH58 and FMI09 gates green; proceed to FH59.
