# FMxx — Phase title

**Program:** ff-fleet-mesh-pdca · **Wave:** MW-N · **Executor:** Composer 2.5

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `fleet_server/`, `packaging/`, `scripts/ff-fleet-mesh-pdca/`, `docs/prompts/ff-fleet-mesh-pdca/`, `docs/design/`, `docs/learn-101/`, `docs/reference/`, `tests/`

**Denylist:** `.cursor/plans/*.plan.md`, unrelated repos (unless explicit handoff)

**Granite boundary:** mesh deploy and data movement via Fleet HTTP only — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `feat(ff-fleet-mesh): FMxx short description` (forge-fleet only, unless handoff says otherwise)

## Plan

(One paragraph — acceptance evidence the gate will check.)

## Do

1. (numbered deliverables with file paths)

## Handoff

(Cross-repo or operator runbook gates, when applicable.)

## Check

```bash
cd forge-fleet
./scripts/ff-fleet-mesh-pdca/check-phase-gate.sh FMxx
```

## Act

Remediate until gate is green; proceed to next phase only.
