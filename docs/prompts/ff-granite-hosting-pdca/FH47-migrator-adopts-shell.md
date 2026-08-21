# FH47 — forge-migrator adopts shell

**Program:** ff-granite-hosting-pdca · **Wave:** GW-4 · **Executor:** Composer 2.5  
**Requirements:** R10, R11

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-migrator/desktop/`, `/home/lzvyahin/Code/forge-studio-shell/`

**Denylist:** `.cursor/plans/*.plan.md`, duplicate Electron bootstrap

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `feat(fmigr): adopt forge-studio-shell desktop` (forge-migrator)

## Plan

forge-migrator uses the same `@autowww/forge-studio-shell` package and manifest pattern as forge-market (R10, R11).

## Do

1. Add `studio.config.json` for migrator wizard (health path, port, profile).
2. Replace `forge-migrator/desktop/main.js` with `createStudioApp.run(...)`.
3. Wire `file:../../forge-studio-shell` dependency in migrator desktop package.

## Handoff

GW-4 consumer adoption complete; unblocks **FH48** GW-4 closeout and **FH50** migrator scaffold.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH47
cd /home/lzvyahin/Code/forge-migrator
test -f studio.config.json
grep -q forge-studio-shell desktop/package.json 2>/dev/null || grep -rq forge-studio-shell .
cd /home/lzvyahin/Code/forge-studio-shell
./scripts/fss-studio-shell-pdca/check-phase-gate.sh all
```

## Act

Remediate until FH47 gate green; proceed to FH48.
