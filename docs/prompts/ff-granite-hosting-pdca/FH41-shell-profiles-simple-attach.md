# FH41 — Shell profiles simple attach (FSS02)

**Program:** ff-granite-hosting-pdca · **Wave:** GW-4 · **Executor:** Composer 2.5  
**Requirements:** R11

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-studio-shell/` (sub-program FSS02)

**Denylist:** `.cursor/plans/*.plan.md`, consumer repo desktop migrations

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `feat(fss): FSS02 shell profiles` (forge-studio-shell)

## Plan

**FSS02** adds `run(configPath)` and profile values: `simple`, `attach-or-spawn`, `attach-only`, `spawn-only` (R11).

## Do

1. Execute `/home/lzvyahin/Code/forge-studio-shell/docs/prompts/fss-studio-shell-pdca/FSS02-consumer-desktop.md`.
2. Export `run(configPath)` from `lib/createStudioApp.js`.
3. Document profile field in schema.

## Handoff

Sub-program **FSS02** ↔ coordinator **FH41**. Unblocks **FH42** / FSS03.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH41
cd /home/lzvyahin/Code/forge-studio-shell
./scripts/fss-studio-shell-pdca/check-phase-gate.sh FSS02
```

## Act

Remediate until FH41 and FSS02 gates green; proceed to FH42.
