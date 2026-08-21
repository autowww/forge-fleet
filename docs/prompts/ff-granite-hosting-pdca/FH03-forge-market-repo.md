# FH03 — forge-market repo visibility and branch

**Program:** ff-granite-hosting-pdca · **Wave:** GW-0 · **Executor:** Composer 2.5  
**Requirement:** R12

## Plan

`autowww/forge-market` is **private**. Integration branch `feature/fleet-postgres-hosting` exists (or documented equivalent). Sub-program scaffold stub `fm-postgres-hosting-pdca` referenced from coordinator master sequence.

## Agent isolation

**Allowlist:** GitHub repo settings/branch for `autowww/forge-market`, `docs/prompts/ff-granite-hosting-pdca/`

**Denylist:** Large feature implementation (Postgres factory belongs to GW-3), `.cursor/plans/`

## Do

1. Set `autowww/forge-market` repository visibility to **private** (`gh repo edit --visibility private`).
2. Create branch `feature/fleet-postgres-hosting` from current main if it does not exist.
3. Add stub `docs/prompts/fm-postgres-hosting-pdca/README.md` on that branch pointing to coordinator FH30–FH38 / FMH01–FMH08.
4. Record branch name in coordinator handoff note for GW-3 entry.

## Handoff

Unblocks **GW-3** (`fm-postgres-hosting-pdca`).

## Check

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH03
```

## Act

Remediate until FH03 gate is green; proceed to FH04.
