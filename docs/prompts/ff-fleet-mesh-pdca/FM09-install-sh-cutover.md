# FM09 — install.sh cutover

**Program:** ff-fleet-mesh-pdca · **Wave:** MW-0b · **Executor:** Composer 2.5  
**Requirements:** R10, R1a, R06f, R09b, NFR08

## Plan

`packaging/ubuntu/install.sh` bootstraps apt source from `$HOME`; noble integration test installs `forge-fleet-user` and returns health 200 on `:18766` without git.

## Do

1. Add `packaging/ubuntu/install.sh` with `--user`, `--system`, `--with-docker` flags.
2. Optional `FLEET_VERIFY_CHECKSUMS=1` verifies `SHA256SUMS.asc` before apt install.
3. Add `tests/integration/test_apt_install_noble.sh` (or CI job) on `ubuntu:noble`.
4. Publish `install.sh` to CDN alongside debs.

## Check

```bash
cd forge-fleet
./scripts/ff-fleet-mesh-pdca/check-phase-gate.sh FM09
```

## Act

Remediate until FM09 gate is green; proceed to FM10 (POST forward).
