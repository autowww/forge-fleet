# FH17 — Market Studio rollout API

**Program:** ff-granite-hosting-pdca · **Wave:** GW-1 · **Executor:** Composer 2.5  
**Requirements:** R02, R23

## Plan

``POST /v1/admin/forge-market-studio-rollout`` schedules local compose rollout (no SSH) via ``scripts/rollout-forge-market-studio.sh``.

## Do

1. Add ``fleet_server/forge_market_studio_rollout.py`` mirroring forge-llm rollout module.
2. Add ``scripts/rollout-forge-market-studio.sh`` (register ``forge_market_studio`` service).
3. Wire route in ``fleet_server/main.py``.

## Check

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH17
pytest tests/test_forge_market_studio_rollout.py -q
```

## Act

Remediate until FH17 gate is green; proceed to FH18.
