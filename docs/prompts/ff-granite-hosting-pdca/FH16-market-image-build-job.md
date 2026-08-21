# FH16 — Market image build job

**Program:** ff-granite-hosting-pdca · **Wave:** GW-1 · **Executor:** Composer 2.5  
**Requirement:** R23

## Plan

Fleet job template ``build_market_image`` builds ``forge-market-app:studio`` on Granite without SSH (stub in GW-1; full template in GW-2/GW-5).

## Do

1. Document expected job argv / env in ``docs/build-201/08-managed-compose-services.md`` (build via rollout or future migration job).
2. Stub job template reference for ``forge-migrator`` recipe step ``build_image``.

## Check

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH16
```

## Act

Remediate until FH16 gate is green; proceed to FH17.
