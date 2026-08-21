# FH48 — GW-4 wave closeout

**Program:** ff-granite-hosting-pdca · **Wave:** GW-4 · **Executor:** Composer 2.5

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`

**Denylist:** `.cursor/plans/*.plan.md`

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `feat(ff-granite): FH48 GW-4 closeout` (coordinator verification)

## Plan

GW-4 exit: FSS01–FSS06 gates green; forge-market and forge-migrator desktop adoption verified; coordinator FH40–FH47 green.

## Do

1. Run `./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH47`.
2. Run `./scripts/ff-granite-hosting-pdca/check-phase-gate.sh GW-4`.
3. Confirm forge-studio-shell `check-phase-gate.sh all` green.
4. Confirm forge-market and forge-migrator use shared shell package.

## Handoff

GW-4 complete; unblocks **GW-5** (FH50 forge-migrator wizard).

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH48
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh GW-4
cd /home/lzvyahin/Code/forge-studio-shell
./scripts/fss-studio-shell-pdca/check-phase-gate.sh all
```

## Act

Remediate until FH48 and GW-4 gates green; proceed to FH50 (GW-5).
