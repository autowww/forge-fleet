# FH59 — GW-5 wave closeout

**Program:** ff-granite-hosting-pdca · **Wave:** GW-5 · **Executor:** Composer 2.5

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`

**Denylist:** `.cursor/plans/*.plan.md`, Granite SSH deploy/data commands

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `feat(ff-granite): FH59 GW-5 closeout` (coordinator verification)

## Plan

GW-5 exit: FMI01–FMI10 gates green; forge-market recipe + generic fixture run; coordinator FH50–FH58 verified.

## Do

1. Run `./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH58`.
2. Run `./scripts/ff-granite-hosting-pdca/check-phase-gate.sh GW-5`.
3. In `/home/lzvyahin/Code/forge-migrator`, run `./scripts/fmigr-wizard-pdca/check-phase-gate.sh all`.
4. Confirm second dummy recipe (FMI08) executes without forge-market-specific hardcoding.

## Handoff

GW-5 complete; unblocks **GW-6** Granite cutover (FH60).

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH59
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh GW-5
cd /home/lzvyahin/Code/forge-migrator
./scripts/fmigr-wizard-pdca/check-phase-gate.sh all
```

## Act

Remediate until FH59 and GW-5 gates green; proceed to FH60 (GW-6).
