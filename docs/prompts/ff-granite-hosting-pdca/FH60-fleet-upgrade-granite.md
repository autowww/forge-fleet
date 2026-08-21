# FH60 — Fleet upgrade on Granite

**Program:** ff-granite-hosting-pdca · **Wave:** GW-6 · **Executor:** Composer 2.5  
**Requirements:** R06

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `docs/build-201/`, `scripts/update-fleet.sh`, `docs/design/granite-operator-boundary.md`

**Denylist:** `.cursor/plans/*.plan.md`, **`scp`/`rsync`/manual bundle transfer via SSH**, manual `docker compose` on Granite, SSH data or deploy ops for Market Studio

**Granite SSH:** allowed **ONLY** for Fleet daemon upgrade when `POST /v1/admin/git-self-update` is insufficient (e.g. `system_install_requires_root`). **NO file transfer via SSH.** Preferred path: `./scripts/update-fleet.sh --remote-git-self-update`. SSH fallback runs documented install/update only (`git pull`, `./update-user.sh` / `install-update.sh`) — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `docs(ff-granite): FH60 fleet upgrade runbook` (forge-fleet)

## Plan

Document and verify Granite Fleet upgrade path: API self-update first; SSH **only** for daemon install when API blocked. Explicitly forbid SSH file transfer (R06).

## Do

1. Add operator runbook section in `docs/build-201/` for Granite Fleet upgrade (API-first, SSH fallback).
2. Document `./scripts/update-fleet.sh --remote-git-self-update` as primary path.
3. Document SSH fallback: **Fleet daemon upgrade only** — no `scp`, `rsync`, bundle extract, or Market Studio deploy via SSH.
4. Cross-link [granite-operator-boundary.md](../../design/granite-operator-boundary.md).

## Handoff

Unblocks staging migration dry run (**FH61**); all cutover steps remain API-only.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH60
./scripts/ff-granite-hosting-pdca/check-granite-boundary.sh
grep -q 'git-self-update' docs/design/granite-operator-boundary.md
grep -q 'NO file transfer' docs/design/granite-operator-boundary.md || grep -q 'Forbidden on Granite SSH' docs/design/granite-operator-boundary.md
test -f scripts/update-fleet.sh
```

## Act

Remediate until FH60 gate and boundary lint green; proceed to FH61. **Never use SSH for data transfer.**
