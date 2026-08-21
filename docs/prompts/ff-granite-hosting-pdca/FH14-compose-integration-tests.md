# FH14 — Compose integration tests

**Program:** ff-granite-hosting-pdca · **Wave:** GW-1 · **Executor:** Composer 2.5  
**Requirement:** R16

## Plan

Mocked subprocess tests cover ``managed_compose_service`` and preserve forge-llm regression coverage.

## Do

1. Add ``tests/test_managed_compose_service.py`` (resolve, ps, start/stop, market port parse).
2. Keep ``tests/test_forge_llm_service.py`` green (gateway helpers + status wrapper).

## Check

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH14
pytest tests/test_managed_compose_service.py tests/test_forge_llm_service.py -q
```

## Act

Remediate until FH14 gate is green; proceed to FH15.
