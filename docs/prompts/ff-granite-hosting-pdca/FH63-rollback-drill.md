# FH63 — Rollback drill

**Program:** ff-granite-hosting-pdca · **Wave:** GW-6 · **Executor:** Composer 2.5  
**Requirements:** R21

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `docs/build-201/09-migration-api.md`, `fleet_server/migration_jobs.py`

**Denylist:** `.cursor/plans/*.plan.md`, Granite SSH volume restore, manual bundle extract via SSH

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `docs(ff-granite): FH63 rollback drill evidence` (forge-fleet)

## Plan

Rollback via Fleet API: stop service + `restore_from_bundle` migration job; e2e in staging (R21).

## Do

1. Execute rollback drill using migrator recipe rollback steps.
2. Verify `restore_from_bundle` job template in `fleet_server/migration_jobs.py`.
3. Document operator steps in migration API runbook.

## Handoff

Unblocks **FH64** handbooks and OpenAPI sync.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH63
grep -q restore_from_bundle fleet_server/migration_jobs.py
pytest tests/test_migrations_api.py -q
cd /home/lzvyahin/Code/forge-migrator
./scripts/fmigr-wizard-pdca/check-phase-gate.sh FMI07
```

## Act

Remediate until FH63 gate green; proceed to FH64.
