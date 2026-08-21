# FH18 — GW-1 wave closeout

**Program:** ff-granite-hosting-pdca · **Wave:** GW-1 · **Executor:** Composer 2.5

## Plan

GW-1 exit: ``forge_llm`` and ``forge_market_studio`` coexist; gates FH10–FH17 green; GW-1 aggregate gate passes.

## Do

1. Run ``./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH17``.
2. Run ``./scripts/ff-granite-hosting-pdca/check-phase-gate.sh GW-1``.
3. Confirm ``managed_compose_service`` + Market Studio deploy tree + rollout API present.

## Check

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH18
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh GW-1
pytest tests/test_managed_compose_service.py tests/test_forge_llm_service.py tests/test_forge_market_studio_rollout.py -q
```

## Act

Remediate until FH18 and GW-1 gates green; proceed to FH20 (GW-2).
