# FH55 — Cursor SDK integration (FMI06)

**Program:** ff-granite-hosting-pdca · **Wave:** GW-5 · **Executor:** Composer 2.5  
**Requirements:** R08

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-migrator/` (sub-program FMI06)

**Denylist:** `.cursor/plans/*.plan.md`, unbounded agent file access outside recipe allowlist

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `feat(fmigr): FMI06 cursor SDK integration` (forge-migrator)

## Plan

**FMI06** stubs `integrations/cursor/run_agent.py` for AI-tagged local recipe steps with allowlist/denylist (R08).

## Do

1. Execute `/home/lzvyahin/Code/forge-migrator/docs/prompts/fmigr-wizard-pdca/FMI06-cursor-sdk-integration.md`.
2. Add agent panel in migrator UI.
3. Enforce path allowlist/denylist on agent steps.

## Handoff

Sub-program **FMI06** ↔ coordinator **FH55**. Unblocks **FH56** / FMI07.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH55
cd /home/lzvyahin/Code/forge-migrator
./scripts/fmigr-wizard-pdca/check-phase-gate.sh FMI06
```

## Act

Remediate until FH55 and FMI06 gates green; proceed to FH56.
