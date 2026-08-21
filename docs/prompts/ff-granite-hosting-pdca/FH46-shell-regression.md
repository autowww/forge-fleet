# FH46 — Shell regression (FSS06)

**Program:** ff-granite-hosting-pdca · **Wave:** GW-4 · **Executor:** Composer 2.5  
**Requirements:** R11

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-studio-shell/` (sub-program FSS06), `/home/lzvyahin/Code/forge-market/desktop/`

**Denylist:** `.cursor/plans/*.plan.md`

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `test(fss): FSS06 shell regression` (forge-studio-shell)

## Plan

**FSS06** closeout: all FSS gates green; Electron smoke both profiles; schema documents profile field (R11).

## Do

1. Execute `/home/lzvyahin/Code/forge-studio-shell/docs/prompts/fss-studio-shell-pdca/FSS06-closeout.md`.
2. Ensure FSS02–FSS05 prompts exist and gates pass.
3. Run Electron smoke for `simple` and `attach-or-spawn` profiles.

## Handoff

Sub-program **FSS06** ↔ coordinator **FH46**. Unblocks **FH47** (forge-migrator adopts shell).

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH46
cd /home/lzvyahin/Code/forge-studio-shell
./scripts/fss-studio-shell-pdca/check-phase-gate.sh all
```

## Act

Remediate until FH46 and FSS06 gates green; proceed to FH47.
