# FM07 — forge-fleet-docker meta-package

**Program:** ff-fleet-mesh-pdca · **Wave:** MW-0b · **Executor:** Composer 2.5  
**Requirements:** R09, Q08

## Plan

`forge-fleet-docker` meta-package adds Docker CE official apt source and installs `docker-ce`, buildx, and compose plugins when operator passes `--with-docker` to `install.sh`.

## Do

1. Implement `forge-fleet-docker` postinst mirroring [03-host-bootstrap.md](../../learn-101/03-host-bootstrap.md).
2. Wire `install.sh --with-docker` to `apt install forge-fleet-docker`.
3. Document that Docker CE is not in Ubuntu main — meta-package is optional.

## Check

```bash
cd forge-fleet
./scripts/ff-fleet-mesh-pdca/check-phase-gate.sh FM07
```

## Act

Remediate until FM07 gate is green; proceed to FM08.
