# FH61 — Staging migration dry run

**Program:** ff-granite-hosting-pdca · **Wave:** GW-6 · **Executor:** Composer 2.5  
**Requirements:** R04, R05

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `docs/build-201/09-migration-api.md`

**Denylist:** `.cursor/plans/*.plan.md`, Granite SSH deploy/data ops, `scp`/`rsync` for bundles

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `docs(ff-granite): FH61 staging dry run evidence` (forge-fleet)

## Plan

Run forge-migrator `recipes/forge-market.yaml` against **staging** Fleet; all deploy and data steps via API only (R04, R05).

## Do

1. Execute staging dry run with migrator wizard (`/home/lzvyahin/Code/forge-migrator`).
2. Verify bundle upload bytes match local backup inventory.
3. Record evidence in operator runbook — **no SSH data operations**.

## Handoff

Unblocks **FH62** production cutover.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH61
./scripts/ff-granite-hosting-pdca/check-granite-boundary.sh
cd /home/lzvyahin/Code/forge-migrator
./scripts/fmigr-wizard-pdca/check-phase-gate.sh FMI07
pytest tests/test_migrations_api.py -q
```

## Act

Remediate until FH61 gate green; proceed to FH62.
