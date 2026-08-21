# FH64 — Handbooks and OpenAPI

**Program:** ff-granite-hosting-pdca · **Wave:** GW-6 · **Executor:** Composer 2.5  
**Requirements:** R17, R18

**Allowlist:** `docs/build-201/`, `docs/prompts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-market/docs/handbook/`, `/home/lzvyahin/Code/forge-migrator/docs/`

**Denylist:** `.cursor/plans/*.plan.md`, unrelated product code

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `docs(ff-granite): FH64 handbooks and OpenAPI sync` (multi-repo docs)

## Plan

Fleet handbook + OpenAPI document migration API and managed compose; Market + Migrator handbooks aligned (R17, R18).

## Do

1. Update `docs/build-201/08-managed-compose-services.md` and `09-migration-api.md`.
2. Sync OpenAPI paths for migration + rollout endpoints.
3. In `/home/lzvyahin/Code/forge-market`, update operator/system market-studio handbook pages.
4. In `/home/lzvyahin/Code/forge-migrator`, document wizard operator flow.

## Handoff

Unblocks **FH65** granite boundary audit.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH64
test -f docs/build-201/08-managed-compose-services.md
test -f docs/build-201/09-migration-api.md
cd /home/lzvyahin/Code/forge-market
grep -rq market-studio docs/handbook/ || true
cd /home/lzvyahin/Code/forge-migrator
test -d docs || test -f README.md
```

## Act

Remediate until FH64 gate green; proceed to FH65.
