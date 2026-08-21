# FH51 — Recipe schema engine (FMI02)

**Program:** ff-granite-hosting-pdca · **Wave:** GW-5 · **Executor:** Composer 2.5  
**Requirements:** R07

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-migrator/` (sub-program FMI02)

**Denylist:** `.cursor/plans/*.plan.md`

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `feat(fmigr): FMI02 recipe schema engine` (forge-migrator)

## Plan

**FMI02** ships YAML recipe loading, DAG validation, and `RecipeEngine` step dispatch (R07).

## Do

1. Execute `/home/lzvyahin/Code/forge-migrator/docs/prompts/fmigr-wizard-pdca/FMI02-recipe-schema-engine.md`.
2. Add recipe schema and DAG validator.
3. Add `tests/test_recipe_engine.py`.

## Handoff

Sub-program **FMI02** ↔ coordinator **FH51**. Unblocks **FH52** / FMI03.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH51
cd /home/lzvyahin/Code/forge-migrator
./scripts/fmigr-wizard-pdca/check-phase-gate.sh FMI02
pytest tests/test_recipe_engine.py -q
```

## Act

Remediate until FH51 and FMI02 gates green; proceed to FH52.
