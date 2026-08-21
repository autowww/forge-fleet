# FH52 — Fleet client (FMI03)

**Program:** ff-granite-hosting-pdca · **Wave:** GW-5 · **Executor:** Composer 2.5  
**Requirements:** R04, R05

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-migrator/` (sub-program FMI03)

**Denylist:** `.cursor/plans/*.plan.md`, Granite SSH deploy/data transfer, direct SSH curl substitutes

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `feat(fmigr): FMI03 fleet client` (forge-migrator)

## Plan

**FMI03** ships bearer HTTP client for `/v1/migrations` using Fleet base URL + token (R04, R05).

## Do

1. Execute `/home/lzvyahin/Code/forge-migrator/docs/prompts/fmigr-wizard-pdca/FMI03-fleet-client.md`.
2. Implement client for `POST/GET /v1/migrations` and `PUT …/data-bundle`.
3. Read credentials from env (`FLEET_BASE_URL`, `FLEET_BEARER_TOKEN`).

## Handoff

Sub-program **FMI03** ↔ coordinator **FH52**. Requires GW-2 migration API (FH20–FH28). Unblocks **FH53** / FMI04.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH52
pytest tests/test_migrations_api.py -q
cd /home/lzvyahin/Code/forge-migrator
./scripts/fmigr-wizard-pdca/check-phase-gate.sh FMI03
```

## Act

Remediate until FH52 and FMI03 gates green; proceed to FH53.
