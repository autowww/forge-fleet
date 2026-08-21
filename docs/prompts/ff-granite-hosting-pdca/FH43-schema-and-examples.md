# FH43 — Schema and examples (FSS04)

**Program:** ff-granite-hosting-pdca · **Wave:** GW-4 · **Executor:** Composer 2.5  
**Requirements:** R11

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-studio-shell/` (sub-program FSS04)

**Denylist:** `.cursor/plans/*.plan.md`

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `feat(fss): FSS04 preload IPC tiers` (forge-studio-shell)

## Plan

**FSS04** ships shared preload bridge and window chrome IPC handlers (Tier-1/2 preload APIs) (R11).

## Do

1. Execute `/home/lzvyahin/Code/forge-studio-shell/docs/prompts/fss-studio-shell-pdca/FSS04-preload-ipc.md`.
2. Implement `preload/studioElectron.js` with `contextBridge` minimize/close.
3. Register handlers in `lib/windowIpc.js`.

## Handoff

Sub-program **FSS04** ↔ coordinator **FH43**. Unblocks **FH44** / FSS05.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH43
cd /home/lzvyahin/Code/forge-studio-shell
./scripts/fss-studio-shell-pdca/check-phase-gate.sh FSS04
```

## Act

Remediate until FH43 and FSS04 gates green; proceed to FH44.
