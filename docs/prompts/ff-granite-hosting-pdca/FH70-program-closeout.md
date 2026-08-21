# FH70 — Program closeout

**Program:** ff-granite-hosting-pdca · **Wave:** GW-6 · **Executor:** Composer 2.5  
**Requirements:** R01, R02, R03, R04, R05, R06, R07, R08, R09, R10, R11, R12, R13, R14, R15, R16, R17, R18, R19, R20, R21, R22, R23, R24

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `docs/build-201/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-market/`, `/home/lzvyahin/Code/forge-studio-shell/`, `/home/lzvyahin/Code/forge-migrator/`

**Denylist:** `.cursor/plans/*.plan.md`

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `feat(ff-granite): FH70 program closeout` (coordinator verification)

## Plan

Final program gate: all waves GW-0–GW-6 green; requirements trace matrix **R01–R24** each has gate evidence in [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md); sub-program closeouts verified.

## Do

1. Run `./scripts/ff-granite-hosting-pdca/check-phase-gate.sh all`.
2. Verify requirements ledger rows **R01–R24** populated with phase mapping and gate evidence.
3. Confirm sub-program gates:
   - `/home/lzvyahin/Code/forge-market` — `./scripts/fm-postgres-hosting-pdca/check-phase-gate.sh FMH08`
   - `/home/lzvyahin/Code/forge-studio-shell` — `./scripts/fss-studio-shell-pdca/check-phase-gate.sh all`
   - `/home/lzvyahin/Code/forge-migrator` — `./scripts/fmigr-wizard-pdca/check-phase-gate.sh all`
4. Run `./scripts/ff-granite-hosting-pdca/check-granite-boundary.sh`.
5. Confirm `forge_llm` regression tests still green (R16): `pytest tests/test_forge_llm_service.py -q`.

## Handoff

Program **ff-granite-hosting-pdca** complete. FM-ENT-004 implemented; Granite hosting operator boundary enforced.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH70
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh all
./scripts/ff-granite-hosting-pdca/check-granite-boundary.sh
grep -E '\| R(0[1-9]|1[0-9]|2[0-4]) \|' docs/prompts/ff-granite-hosting-pdca/00_shared/00-requirements-ledger.md | wc -l
pytest tests/test_managed_compose_service.py tests/test_forge_llm_service.py tests/test_migrations_api.py tests/test_forge_market_studio_rollout.py -q
cd /home/lzvyahin/Code/forge-market
./scripts/fm-postgres-hosting-pdca/check-phase-gate.sh FMH08
cd /home/lzvyahin/Code/forge-studio-shell
./scripts/fss-studio-shell-pdca/check-phase-gate.sh all
cd /home/lzvyahin/Code/forge-migrator
./scripts/fmigr-wizard-pdca/check-phase-gate.sh all
```

## Act

Remediate until FH70 and `check-phase-gate.sh all` green; program **ff-granite-hosting-pdca** closed.
