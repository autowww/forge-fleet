# FH62 — Production cutover

**Program:** ff-granite-hosting-pdca · **Wave:** GW-6 · **Executor:** Composer 2.5  
**Requirements:** R04, R05, R24

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `docs/build-201/`, `fleet_server/migration_jobs.py`

**Denylist:** `.cursor/plans/*.plan.md`, Granite SSH deploy/data/route ops, manual Caddy edits via SSH

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `docs(ff-granite): FH62 production cutover runbook` (forge-fleet)

## Plan

Full forge-market recipe on production backup; edge route registered via Fleet `register_edge_route` step; HTTPS probe via migrator (R04, R05, R24).

## Do

1. Run production cutover recipe through forge-migrator against production Fleet.
2. Verify `register_edge_route` migration step completes (FH27).
3. HTTPS probe Market Studio via migrator test panel — no SSH edge edits.

## Handoff

Unblocks **FH63** rollback drill.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH62
./scripts/ff-granite-hosting-pdca/check-granite-boundary.sh
grep -q register_edge_route fleet_server/migration_jobs.py
cd /home/lzvyahin/Code/forge-migrator
test -f recipes/forge-market.yaml
```

## Act

Remediate until FH62 gate green; proceed to FH63.
