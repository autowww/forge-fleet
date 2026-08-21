# FH10 — managed_compose_service refactor

**Program:** ff-granite-hosting-pdca · **Wave:** GW-1 · **Executor:** Composer 2.5  
**Requirements:** R01, R16

## Plan

Generic compose operations live in ``fleet_server/managed_compose_service.py``; ``forge_llm_service`` keeps LLM-specific gateway enrichment only.

## Agent isolation

**Allowlist:** `fleet_server/managed_compose_service.py`, `fleet_server/forge_llm_service.py`, `tests/`

## Do

1. Extract ``compose_ps``, ``start_for_record``, ``stop_for_record``, ``resolve_compose_files`` into ``managed_compose_service.py``.
2. Extend allowed overlay list with ``compose.granite.yaml`` and ``compose.market.yaml``.
3. Re-export or wrap from ``forge_llm_service`` without breaking existing imports.

## Check

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH10
pytest tests/test_managed_compose_service.py tests/test_forge_llm_service.py -q
```

## Act

Remediate until FH10 gate is green; proceed to FH11.
