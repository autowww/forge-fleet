# FH02 — forge-studio-shell repo bootstrap

**Program:** ff-granite-hosting-pdca · **Wave:** GW-0 · **Executor:** Composer 2.5  
**Requirement:** R11

## Plan

Private `autowww/forge-studio-shell` repo exists with minimal Electron package skeleton and sub-program scaffold stub (`fss-studio-shell-pdca` README or pointer in coordinator master sequence).

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/`, GitHub `autowww/forge-studio-shell` (create if missing)

**Denylist:** forge-market implementation, Fleet runtime code, `.cursor/plans/`

## Do

1. Create private GitHub repo `autowww/forge-studio-shell` (or confirm it exists).
2. Add minimal skeleton: `package.json`, `README.md`, `desktop/main.js` placeholder, `docs/prompts/fss-studio-shell-pdca/README.md` stub pointing to coordinator FH40–FH48.
3. Record repo URL and visibility in forge-fleet handoff note under `docs/prompts/ff-granite-hosting-pdca/00_shared/` if needed for gate evidence.
4. Do not implement FSS01+ behavior in this phase — scaffold only.

## Handoff

Unblocks **GW-4** (`fss-studio-shell-pdca` FSS01–FSS06).

## Check

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH02
```

## Act

Remediate until FH02 gate is green; proceed to FH03.
