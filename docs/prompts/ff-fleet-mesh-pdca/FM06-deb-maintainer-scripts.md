# FM06 — deb maintainer scripts

**Program:** ff-fleet-mesh-pdca · **Wave:** MW-0b · **Executor:** Composer 2.5  
**Requirements:** R06c, R06d, R06g, R09a

## Plan

Debian maintainer scripts implement install/upgrade/remove/purge lifecycle; `forge-fleet.env` is a conffile; `remove` keeps SQLite state; `purge` optionally deletes state via debconf.

## Do

1. Add `packaging/debian-scripts/` or nfpm hooks: `preinst`, `postinst`, `prerm`, `postrm` per package.
2. Register `/etc/forge-fleet/forge-fleet.env` and user env path as conffiles.
3. Document operator `apt install|upgrade|remove|purge` behavior in `docs/learn-101/operator-apt-install.md`.

## Check

```bash
cd forge-fleet
./scripts/ff-fleet-mesh-pdca/check-phase-gate.sh FM06
```

## Act

Remediate until FM06 gate is green; proceed to FM07.
