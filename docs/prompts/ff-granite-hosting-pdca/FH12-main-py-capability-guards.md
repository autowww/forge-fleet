# FH12 — main.py capability guards

**Program:** ff-granite-hosting-pdca · **Wave:** GW-1 · **Executor:** Composer 2.5  
**Requirements:** R01, R16

## Plan

Start/stop/status for container services use ``api_manage_services`` capability instead of hard-coded ``forge_llm`` checks. Legacy ``/v1/services/forge-llm/*`` unchanged.

## Do

1. Add ``_managed_compose_record`` helper in ``fleet_server/main.py``.
2. Route ``POST …/container-services/{id}/start|stop`` through ``managed_compose_service``.
3. Attach status on GET for all API-manageable types; use ``forge_llm_service.status_for_record`` only for ``forge_llm``.

## Check

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH12
```

## Act

Remediate until FH12 gate is green; proceed to FH13.
