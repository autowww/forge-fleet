# FH44 — npm publish shell package (FSS05)

**Program:** ff-granite-hosting-pdca · **Wave:** GW-4 · **Executor:** Composer 2.5  
**Requirements:** R11

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-studio-shell/` (sub-program FSS05)

**Denylist:** `.cursor/plans/*.plan.md`, unpublished breaking API changes without semver note

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `feat(fss): FSS05 npm publish checklist` (forge-studio-shell)

## Plan

**FSS05** prepares `@autowww/forge-studio-shell` for consumer adoption: market migration pattern documented; publish checklist ready (R11).

## Do

1. Execute `/home/lzvyahin/Code/forge-studio-shell/docs/prompts/fss-studio-shell-pdca/FSS05-market-migration.md`.
2. Document consumer `file:../../forge-studio-shell` dependency pattern.
3. Add npm publish checklist to closeout docs (package name, version, files field).

## Handoff

Sub-program **FSS05** ↔ coordinator **FH44**. Unblocks **FH45** (forge-market adopts shell).

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH44
cd /home/lzvyahin/Code/forge-studio-shell
./scripts/fss-studio-shell-pdca/check-phase-gate.sh FSS05
test -f schemas/studio.config.schema.json
```

## Act

Remediate until FH44 and FSS05 gates green; proceed to FH45.
