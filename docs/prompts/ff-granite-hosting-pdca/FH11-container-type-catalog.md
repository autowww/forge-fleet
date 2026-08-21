# FH11 — Container type catalog forge_market_studio

**Program:** ff-granite-hosting-pdca · **Wave:** GW-1 · **Executor:** Composer 2.5  
**Requirement:** R01

## Plan

``DEFAULT_TYPES`` includes ``forge_market_studio`` under the **service** category with ``api_manage_services`` inherited.

## Do

1. Add ``forge_market_studio`` row to ``fleet_server/container_layout.py`` ``DEFAULT_TYPES``.
2. Verify ``GET /v1/container-types`` materializes capabilities for the new type.

## Check

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH11
pytest tests/test_container_layout.py -q
```

## Act

Remediate until FH11 gate is green; proceed to FH12.
