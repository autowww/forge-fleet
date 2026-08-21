# FH37 — Edge sync ADR (FMH08)

**Program:** ff-granite-hosting-pdca · **Wave:** GW-3 · **Executor:** Composer 2.5  
**Requirements:** R20

Read [00-master-sequence.md](00-master-sequence.md) and [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md). Prior gate must be green before starting.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, `scripts/ff-granite-hosting-pdca/`, `/home/lzvyahin/Code/forge-market/` (sub-program FMH08)

**Denylist:** `.cursor/plans/*.plan.md`, Granite SSH edge config edits

**Granite SSH:** allowed **only** for Fleet daemon upgrade when API self-update is blocked — **NO file transfer via SSH** — see [granite-operator-boundary.md](../../design/granite-operator-boundary.md)

**Commit:** `docs(fm-postgres): FMH08 edge sync ADR` (forge-market)

## Plan

**FMH08** documents CDP/IBKR edge execution vs cloud Postgres store split; handbook limits section present (R20).

## Do

1. Execute `/home/lzvyahin/Code/forge-market/docs/prompts/fm-postgres-hosting-pdca/FMH08-edge-sync-adr.md`.
2. Create `docs/design/edge-sync-cloud-adr.md`.
3. Update handbook operator/system pages with Fleet hosting section.

## Handoff

Sub-program **FMH08** ↔ coordinator **FH37**. Unblocks **FH38** GW-3 closeout.

## Check

```bash
cd /home/lzvyahin/Code/forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH37
cd /home/lzvyahin/Code/forge-market
./scripts/fm-postgres-hosting-pdca/check-phase-gate.sh FMH08
pytest tests/ -k postgres -q
```

## Act

Remediate until FH37 and FMH08 gates green; proceed to FH38.
