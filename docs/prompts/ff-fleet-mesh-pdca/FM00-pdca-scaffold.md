# FM00 — PDCA scaffold

**Program:** ff-fleet-mesh-pdca · **Wave:** MW-0 · **Executor:** Composer 2.5

## Plan

Harness files exist; master sequence lists waves MW-0–MW-5 and phases FM00–FM59; Composer 2.5 declared; gate runner wired; requirements ledger R00–R54 and NFR01–NFR08 documented.

## Do

1. Read [00-master-sequence.md](00-master-sequence.md) for wave context.
2. Confirm `scripts/ff-fleet-mesh-pdca/` has `SEQUENCE.yaml`, `check-phase-gate.sh`.
3. Confirm `00_shared/00-requirements-ledger.md`, `01-assumptions-and-non-goals.md`, `02-open-questions-ledger.md` exist.
4. Confirm `_prompt-template.md` and `ORDER.txt` exist.
5. Do not edit `.cursor/plans/*.plan.md`.

## Check

```bash
cd forge-fleet
./scripts/ff-fleet-mesh-pdca/check-phase-gate.sh FM00
```

## Act

Remediate until FM00 gate is green; then proceed to FM01 (peer schema ADR) or FM05 (apt packaging) per program priority.
