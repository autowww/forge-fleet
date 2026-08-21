# FHxx — Phase title

**Program:** ff-granite-hosting-pdca · **Wave:** GW-N · **Executor:** Composer 2.5

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `src/forge_fleet/`, `deploy/`, `tests/`, `docs/build-201/`, `docs/design/`, `docs/prompts/ff-granite-hosting-pdca/`, `scripts/ff-granite-hosting-pdca/`

**Denylist:** `.cursor/plans/*.plan.md`, unrelated repos (unless explicit handoff), Granite SSH deploy/data commands

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `feat(ff-granite): FHxx short description` (forge-fleet only, unless handoff says otherwise)

## Plan

(One paragraph — acceptance evidence the gate will check.)

## Do

1. (numbered deliverables with file paths)

## Handoff

(Sub-program or cross-repo gates, when applicable.)

## Check

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FHxx
./scripts/ff-granite-hosting-pdca/check-granite-boundary.sh   # when runbooks touched
```

## Act

Remediate until gate is green; proceed to next phase only.
