# FH34 — Dockerfile container contract (FMH05)

**Program:** ff-granite-hosting-pdca · **Wave:** GW-3 · **Executor:** Composer 2.5  
**Requirements:** R02, R15

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-market/` (sub-program FMH05), `deploy/forge-market-studio/` (compose alignment only)

**Denylist:** `.cursor/plans/*.plan.md`, Granite SSH image build/push

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `feat(fm-postgres): FMH05 dockerfile container contract` (forge-market)

## Plan

**FMH05** ships root `Dockerfile` + bearer enforcement when `FORGE_MARKET_CONTAINER=1`; aligns with Fleet `deploy/forge-market-studio/` build context (R02, R15).

## Do

1. Execute `/home/lzvyahin/Code/forge-market/docs/prompts/fm-postgres-hosting-pdca/FMH05-dockerfile-container-contract.md`.
2. Create `Dockerfile`, `.dockerignore`, container env contract.
3. Enforce bearer in `forge_market.studio.auth` for container mode.
4. Verify Fleet compose build context still resolves.

## Handoff

Sub-program **FMH05** ↔ coordinator **FH34**. Unblocks Fleet image build job (FH16) and **FH35** / FMH06.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH34
test -f deploy/forge-market-studio/Dockerfile.market-app
cd /home/lzvyahin/Code/forge-market
./scripts/fm-postgres-hosting-pdca/check-phase-gate.sh FMH05
```

## Act

Remediate until FH34 and FMH05 gates green; proceed to FH35.
