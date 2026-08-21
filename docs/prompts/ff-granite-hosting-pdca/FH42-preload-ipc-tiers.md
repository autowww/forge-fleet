# FH42 — Preload IPC tiers (FSS03)

**Program:** ff-granite-hosting-pdca · **Wave:** GW-4 · **Executor:** Composer 2.5  
**Requirements:** R11

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-studio-shell/` (sub-program FSS03)

**Denylist:** `.cursor/plans/*.plan.md`

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `feat(fss): FSS03 health probe contract` (forge-studio-shell)

## Plan

**FSS03** ships shared `/health` probe helpers and attach-only wait path (R11).

## Do

1. Execute `/home/lzvyahin/Code/forge-studio-shell/docs/prompts/fss-studio-shell-pdca/FSS03-health-contract.md`.
2. Keep `probeHealth(port, expectedService, healthPath)` in `lib/httpProbe.js`.
3. Add `waitForAttachedServer()` to `lib/ensureServer.js`.

## Handoff

Sub-program **FSS03** ↔ coordinator **FH42**. Unblocks **FH43** / FSS04.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH42
cd /home/lzvyahin/Code/forge-studio-shell
./scripts/fss-studio-shell-pdca/check-phase-gate.sh FSS03
```

## Act

Remediate until FH42 and FSS03 gates green; proceed to FH43.
