# FH05 — GW-0 wave closeout

**Program:** ff-granite-hosting-pdca · **Wave:** GW-0 · **Executor:** Composer 2.5

## Plan

Wave 0 exit criteria met: harness green, R01–R24 ledger + boundary doc present, three autowww repo bootstraps documented, sub-program scaffolds stubbed in master sequence.

## Agent isolation

**Allowlist:** `docs/prompts/ff-granite-hosting-pdca/`, `docs/design/granite-operator-boundary.md`, `scripts/ff-granite-hosting-pdca/`

## Do

1. Verify gates FH00–FH04 all green: `./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH04`
2. Confirm master sequence cross-links **fm-postgres-hosting-pdca**, **fss-studio-shell-pdca**, **fmigr-wizard-pdca**.
3. Confirm `check-granite-boundary.sh` passes on current runbooks.
4. Add **GW-0 exit** checklist to master sequence (or 00_shared execution note) with phase links FH00–FH04.

## Check

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH05
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh GW-0
```

## Act

Remediate until FH05 and GW-0 gates green; proceed to FH10 (GW-1).
