# Operate 301 — Backup, restore, and disaster recovery

**Audience:** operators responsible for Fleet uptime and data safety.  
**Outcome:** know **what** to back up, **how often**, and **how** to validate a restore.

## What state exists on disk

| Asset | Typical path (varies by install) | Notes |
| --- | --- | --- |
| **SQLite job database** | `{FLEET_DATA_DIR}/fleet.sqlite` | Job rows, logs tails, meta—**primary durability concern** |
| **Container layout** | `{FLEET_DATA_DIR}/etc/containers/` | `types.json`, requirement templates, build cache |
| **Managed services** | `{FLEET_DATA_DIR}/etc/services/` | JSON records for compose-backed services |
| **Logs** | journald / stdout; optional app log files | May contain secrets from job metadata—treat as sensitive |
| **Workspace tarballs** | extracted under data dir per job | Often ephemeral; policy-dependent |
| **Environment / systemd** | `/etc/forge-fleet/forge-fleet.env`, user XDG paths | Tokens, ports, `FLEET_DATA_DIR` |
| **Caddy / TLS** | `/etc/caddy`, `certbot`, etc. | Front-end only—but required for HTTPS recovery |

## Backup cadence

1. **SQLite** — daily file-level snapshot while Fleet is **stopped** or using **online backup** tooling acceptable to your org; copying a hot WAL without SQLite backup API risks corruption under write load.
2. **`etc/containers` + `etc/services`** — version with every intentional catalog change; small text/JSON artifacts.
3. **Configuration** — track **`forge-fleet.env`** in your secrets manager, not only on disk.

## Restore procedure (outline)

1. Install matching **Fleet semver** (or newer with migrations) per **[Upgrade](05-upgrade-release-and-remote-update.md)**.
2. Stop **`forge-fleet.service`**.
3. Restore **`fleet.sqlite`** and **`etc/**`** trees into **`FLEET_DATA_DIR`**.
4. Restore env files and Caddy config if the hostname/TLS setup must match.
5. Start the unit; run **`GET /v1/version`** and **`GET /v1/health`**.
6. Submit a **trivial `docker_argv`** job to prove the runner (**[Learn 101 — First job](../learn-101/06-first-fleet-job.md)**).

## Restore validation

| Check | Pass criteria |
| --- | --- |
| Version endpoint | **`GET /v1/version`** JSON matches expected package |
| Schema migrations | Server starts without SQLite migration errors in logs |
| Job execution | **`hello-world`**-class job reaches **`completed`** |

## Disaster scenarios

| Scenario | Mitigation |
| --- | --- |
| **Lost DB only** | Restore from latest SQLite backup; accept job history gap |
| **Lost data dir** | Restore DB + `etc/` together; without **`etc/containers`**, templates/types must be re-imported |
| **Region / host loss** | Prepare a cold stand-by image: same Fleet version line, restored **`FLEET_DATA_DIR`**, validated TLS + bearer policy |

## Related

- **[Operations runbook](02-operations-runbook.md)** — symptom tables  
- **[Architecture](03-architecture.md)** — data paths  
- **[Security](01-security.md)** — what backups may contain (tokens, workspace content)
