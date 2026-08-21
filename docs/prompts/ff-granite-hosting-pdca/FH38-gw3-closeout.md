# FH38 — GW-3 wave closeout

**Program:** ff-granite-hosting-pdca · **Wave:** GW-3 · **Executor:** Composer 2.5  
**Requirements:** R18

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`

**Denylist:** `.cursor/plans/*.plan.md`, Granite SSH deploy/data commands

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `feat(ff-granite): FH38 GW-3 closeout` (forge-fleet + forge-market handbook)

## Plan

GW-3 exit: FMH01–FMH08 gates green; FM-ENT-004 → **implemented** in feature-index; coordinator FH30–FH37 verified (R18).

## Do

1. Run `./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH37`.
2. Run `./scripts/ff-granite-hosting-pdca/check-phase-gate.sh GW-3`.
3. In `/home/lzvyahin/Code/forge-market`, confirm FM-ENT-004 status **implemented** in `docs/handbook/shared/feature-index.md`.
4. Confirm sub-program gates FMH01–FMH08 all green.

## Handoff

GW-3 complete; unblocks **GW-4** (FH40 forge-studio-shell).

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH38
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh GW-3
cd /home/lzvyahin/Code/forge-market
./scripts/fm-postgres-hosting-pdca/check-phase-gate.sh FMH08
grep -q implemented docs/handbook/shared/feature-index.md
pytest tests/ -k postgres -q
```

## Act

Remediate until FH38 and GW-3 gates green; proceed to FH40 (GW-4).
