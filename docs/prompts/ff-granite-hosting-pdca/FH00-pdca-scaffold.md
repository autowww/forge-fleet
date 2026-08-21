# FH00 — PDCA scaffold

**Program:** ff-granite-hosting-pdca · **Wave:** GW-0 · **Executor:** Composer 2.5

## Plan

Harness files exist; master sequence lists waves GW-0–GW-6 and phases FH00–FH70; Composer 2.5 declared; gate runner and granite boundary checker wired.

## Do

1. Read [00-master-sequence.md](00-master-sequence.md) for wave context.
2. Confirm `scripts/ff-granite-hosting-pdca/` has `SEQUENCE.yaml`, `check-phase-gate.sh`, `pdca-run-phase.sh`, `run-wave.sh`, `check-granite-boundary.sh`.
3. Confirm `_prompt-template.md` and GW-0 phase prompts FH00–FH05 exist.
4. Do not edit `.cursor/plans/*.plan.md`.

## Check

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH00
```

## Act

Remediate until FH00 gate is green; then proceed to FH01.
