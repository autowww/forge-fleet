# FH50 — Migrator scaffold (FMI01)

**Program:** ff-granite-hosting-pdca · **Wave:** GW-5 · **Executor:** Composer 2.5  
**Requirements:** R10

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-migrator/` (sub-program FMI01)

**Denylist:** `.cursor/plans/*.plan.md`, Granite SSH deploy/data commands

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `feat(fmigr): FMI01 migrator scaffold` (forge-migrator)

## Plan

Sub-program **FMI01** ships migrator UI + server + `/health`; studio-shell wired (R10).

## Do

1. Create `/home/lzvyahin/Code/forge-migrator/docs/prompts/fmigr-wizard-pdca/FMI01-migrator-scaffold.md` if missing; execute it.
2. Add migrator server, UI shell, health endpoint.
3. Wire forge-studio-shell desktop entry from FH47.

## Handoff

Sub-program **FMI01** ↔ coordinator **FH50**. Unblocks **FH51** / FMI02.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH50
cd /home/lzvyahin/Code/forge-migrator
./scripts/fmigr-wizard-pdca/check-phase-gate.sh FMI01
curl -fsS http://127.0.0.1:${MIGRATOR_PORT:-9795}/health || true
```

## Act

Remediate until FH50 and FMI01 gates green; proceed to FH51.
