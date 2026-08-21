# FH53 — Progress and logs UI (FMI04)

**Program:** ff-granite-hosting-pdca · **Wave:** GW-5 · **Executor:** Composer 2.5  
**Requirements:** R09

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-migrator/` (sub-program FMI04)

**Denylist:** `.cursor/plans/*.plan.md`

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `feat(fmigr): FMI04 progress and logs UI` (forge-migrator)

## Plan

**FMI04** ships wizard UI with step toggles, run button, live logs, migration polling (R09).

## Do

1. Execute `/home/lzvyahin/Code/forge-migrator/docs/prompts/fmigr-wizard-pdca/FMI04-progress-and-logs-ui.md`.
2. Wire step state machine to Fleet migration GET polling.
3. Surface bytes transferred from migration progress API (R22 partial).

## Handoff

Sub-program **FMI04** ↔ coordinator **FH53**. Unblocks **FH54** / FMI05.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH53
cd /home/lzvyahin/Code/forge-migrator
./scripts/fmigr-wizard-pdca/check-phase-gate.sh FMI04
```

## Act

Remediate until FH53 and FMI04 gates green; proceed to FH54.
