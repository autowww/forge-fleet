# FH45 — forge-market adopts shell

**Program:** ff-granite-hosting-pdca · **Wave:** GW-4 · **Executor:** Composer 2.5  
**Requirements:** R11

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-market/desktop/`, `/home/lzvyahin/Code/forge-studio-shell/`

**Denylist:** `.cursor/plans/*.plan.md`, inline Electron bootstrap duplication

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `feat(fm): adopt forge-studio-shell desktop` (forge-market)

## Plan

Replace forge-market inline Electron bootstrap with `@autowww/forge-studio-shell` manifest + thin `desktop/main.js` (R11).

## Do

1. Add `studio.config.json` from forge-studio-shell market example.
2. Replace `forge-market/desktop/main.js` with `createStudioApp.run(...)`.
3. Add `file:../../forge-studio-shell` dependency in `desktop/package.json`.

## Handoff

Consumer adoption complete; unblocks **FH46** / FSS06 shell regression.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH45
cd /home/lzvyahin/Code/forge-studio-shell
./scripts/fss-studio-shell-pdca/check-phase-gate.sh FSS05
cd /home/lzvyahin/Code/forge-market
test -f studio.config.json
grep -q forge-studio-shell desktop/package.json
```

## Act

Remediate until FH45 gate green; proceed to FH46.
