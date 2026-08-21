# FH13 — Market Studio compose stack

**Program:** ff-granite-hosting-pdca · **Wave:** GW-1 · **Executor:** Composer 2.5  
**Requirement:** R02

## Plan

Ship ``deploy/forge-market-studio/`` with Postgres 16, ``market-app``, named volumes, healthchecks, Granite port overlay, and Dockerfile build contract.

## Do

1. Create ``deploy/forge-market-studio/compose.yaml`` (postgres + market-app + volumes).
2. Create ``compose.granite.yaml`` loopback port overlay.
3. Create ``Dockerfile.market-app`` (build context = forge-market) and ``.env.example``.

## Handoff

Unblocks forge-market **FMH05** (Dockerfile hardening in forge-market repo).

## Check

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH13
```

## Act

Remediate until FH13 gate is green; proceed to FH14.
