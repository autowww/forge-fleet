# FH15 — Container service API docs

**Program:** ff-granite-hosting-pdca · **Wave:** GW-1 · **Executor:** Composer 2.5  
**Requirement:** R17

## Plan

Operator-facing Build 201 chapter documents managed compose types, service records, and rollout paths.

## Do

1. Add ``docs/build-201/08-managed-compose-services.md``.
2. Link from ``docs/build-201/README.md`` topic table.

## Check

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH15
```

## Act

Remediate until FH15 gate is green; proceed to FH16.
