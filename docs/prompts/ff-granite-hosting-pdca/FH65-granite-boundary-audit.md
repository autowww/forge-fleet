# FH65 — Granite boundary audit

**Program:** ff-granite-hosting-pdca · **Wave:** GW-6 · **Executor:** Composer 2.5  
**Requirements:** R06

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `docs/build-201/`, `docs/design/granite-operator-boundary.md`

**Denylist:** `.cursor/plans/*.plan.md`, adding SSH deploy/data instructions to runbooks

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `docs(ff-granite): FH65 granite boundary audit` (forge-fleet)

## Plan

All operator runbooks pass `check-granite-boundary.sh`; no forbidden SSH patterns; R06 evidence complete.

## Do

1. Run `./scripts/ff-granite-hosting-pdca/check-granite-boundary.sh` on all runbooks under `docs/build-201/`.
2. Remediate any `scp`, `rsync`, manual compose, or SSH bundle transfer instructions.
3. Confirm boundary doc lists allowed vs forbidden paths.

## Handoff

Unblocks **FH70** program closeout.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH65
./scripts/ff-granite-hosting-pdca/check-granite-boundary.sh
grep -q R06 docs/prompts/ff-granite-hosting-pdca/00_shared/00-requirements-ledger.md
```

## Act

Remediate until FH65 gate and boundary lint green; proceed to FH70.
