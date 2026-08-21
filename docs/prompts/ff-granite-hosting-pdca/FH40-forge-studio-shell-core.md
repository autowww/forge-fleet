# FH40 — createStudioApp core (FSS01)

**Program:** ff-granite-hosting-pdca · **Wave:** GW-4 · **Executor:** Composer 2.5  
**Requirements:** R11

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-studio-shell/` (sub-program FSS01)

**Denylist:** `.cursor/plans/*.plan.md`, forge-market desktop migration (FH45), Granite SSH

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `feat(fss): FSS01 createStudioApp core` (forge-studio-shell)

## Plan

Sub-program **FSS01** ships config-driven Electron app factory (`createStudioApp`, shared lib modules, schema stub) (R11).

## Do

1. Execute `/home/lzvyahin/Code/forge-studio-shell/docs/prompts/fss-studio-shell-pdca/FSS01-scaffold.md`.
2. Add `lib/createStudioApp.js`, `resolvePython.js`, `httpProbe.js`, `ensureServer.js`, `windowIpc.js`.
3. Add `preload/studioElectron.js`, `schemas/studio.config.schema.json`, example config.

## Handoff

Sub-program **FSS01** ↔ coordinator **FH40**. Unblocks **FH41** / FSS02.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH40
cd /home/lzvyahin/Code/forge-studio-shell
./scripts/fss-studio-shell-pdca/check-phase-gate.sh FSS01
```

## Act

Remediate until FH40 and FSS01 gates green; proceed to FH41.
