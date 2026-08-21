# FH04 — forge-migrator repo bootstrap

**Program:** ff-granite-hosting-pdca · **Wave:** GW-0 · **Executor:** Composer 2.5  
**Requirement:** R10

## Plan

Private `autowww/forge-migrator` repo exists with minimal Electron + server skeleton and sub-program scaffold stub (`fmigr-wizard-pdca` README).

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, GitHub `autowww/forge-migrator` (create if missing)

**Denylist:** Full recipe engine (GW-5), Fleet migration API implementation (GW-2), `.cursor/plans/`

## Do

1. Create private GitHub repo `autowww/forge-migrator` (or confirm it exists).
2. Add minimal skeleton: `package.json`, `README.md`, `desktop/main.js` placeholder, `migrator-server/` health stub, `docs/prompts/fmigr-wizard-pdca/README.md` pointing to coordinator FH50–FH59.
3. Document repo URL in coordinator 00_shared handoff notes if needed for gate evidence.
4. Do not implement FMI01+ wizard behavior in this phase — scaffold only.

## Handoff

Unblocks **GW-5** (`fmigr-wizard-pdca` FMI01–FMI10).

## Check

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH04
```

## Act

Remediate until FH04 gate is green; proceed to FH05.
