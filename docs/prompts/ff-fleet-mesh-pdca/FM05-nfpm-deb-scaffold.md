# FM05 — nfpm deb scaffold

**Program:** ff-fleet-mesh-pdca · **Wave:** MW-0b · **Executor:** Composer 2.5  
**Requirements:** R07, R06h

## Plan

`packaging/nfpm/` builds `forge-fleet`, `forge-fleet-user`, and `forge-fleet-docker` `.deb` artifacts locally; kitchensink CSS subset bundled (no submodule at install).

## Do

1. Add `packaging/nfpm/forge-fleet.yaml`, `forge-fleet-user.yaml`, `forge-fleet-docker.yaml`.
2. Add `packaging/scripts/bundle-kitchensink-css.sh` to copy admin-required CSS into package staging.
3. Document local build: `nfpm package --config packaging/nfpm/forge-fleet-user.yaml`.
4. Version synced from `pyproject.toml`.

## Check

```bash
cd forge-fleet
./scripts/ff-fleet-mesh-pdca/check-phase-gate.sh FM05
```

## Act

Remediate until FM05 gate is green; proceed to FM06.
