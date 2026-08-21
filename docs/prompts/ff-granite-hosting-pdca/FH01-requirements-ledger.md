# FH01 — Requirements ledger and operator boundary

**Program:** ff-granite-hosting-pdca · **Wave:** GW-0 · **Executor:** Composer 2.5  
**Requirements:** R01–R24, R06

## Plan

Requirements ledger lists R01–R24 with phase mapping and gate evidence. Granite operator boundary doc states SSH-only-for-Fleet-upgrade rule and forbidden SSH patterns.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/00_shared/`, `docs/design/granite-operator-boundary.md`, `docs/prompts/ff-granite-hosting-pdca/`

**Denylist:** `.cursor/plans/`, unrelated product code until later waves

## Do

1. Ensure [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md) has rows **R01–R24** with phase(s) and gate evidence columns populated.
2. Ensure [granite-operator-boundary.md](../../design/granite-operator-boundary.md) documents allowed Fleet API paths and forbidden SSH deploy/data operations.
3. Cross-link boundary doc from master sequence and `_prompt-template.md`.
4. Verify `check-granite-boundary.sh` exists and documents scanned runbook paths.

## Check

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH01
./scripts/ff-granite-hosting-pdca/check-granite-boundary.sh
```

## Act

Remediate until FH01 gate is green; proceed to FH02.
