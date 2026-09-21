# FM08 — apt repo publish

**Program:** ff-fleet-mesh-pdca · **Wave:** MW-0b · **Executor:** Composer 2.5  
**Requirements:** R06, R06e, R08

## Plan

CI builds signed apt repository (`dists/noble/`, `pool/`) and publishes to staging CDN at `packages.forgesdlc.com`; GPG archive key in CI secrets only.

## Do

1. Add `packaging/apt/reprepro-conf/` and `scripts/publish-fleet-apt-repo.sh`.
2. CI job on release tag: build debs → `reprepro includedeb noble` → upload `dists/`, `pool/`, `gpg.key`.
3. Generate `SHA256SUMS` + detached signature.

## Check

```bash
cd forge-fleet
./scripts/ff-fleet-mesh-pdca/check-phase-gate.sh FM08
```

## Act

Remediate until FM08 gate is green; proceed to FM09.
