# Operate 301 — Production and reliability

**Purpose:** operate Fleet with clear **trust boundaries**, **day-two procedures**, and **incident ladders**.

| | |
| --- | --- |
| **Audience** | Production operators, SRE-adjacent owners, security reviewers |
| **Effort** | **~1–3 hours** to read core pages; ongoing runbook use |
| **Prerequisites** | **[Build 201](../build-201/README.md)** topics you actually deploy (Caddy, templates, etc.) |
| **Success** | You can answer “who may execute code on this host?”, restart Fleet safely, and walk a **symptom → check → fix** path |

## At a glance

- **You will:** lock down trust boundaries, run day-two checks, and navigate incidents with explicit ladders.
- **Tone:** assume production — prefer checklists and explicit rollback over tutorial pacing.
- **Pair with:** **`CHANGELOG.md`** host-operator notes when cutting releases.

| Topic | Page |
|------|------|
| Trust boundaries + bearer hygiene | **[Security](01-security.md)** |
| Day-two checks (`systemctl`, SQLite, rotations) | **[Operations runbook](02-operations-runbook.md)** |
| Dispatcher diagrams + data paths | **[Architecture](03-architecture.md)** |
| Symptom → fix ladders | **[Troubleshooting](04-troubleshooting.md)** · start at symptom headings |
| Cooperative upgrade (`POST /v1/admin/upgrade`) + apt channel | **[Upgrade & remote operations](05-upgrade-release-and-remote-update.md)** |
| Backup / DR posture | **[Backup, restore & DR](06-backup-restore-and-disaster-recovery.md)** |
| Telemetry, SLOs, alerting | **[Observability & SLOs](07-observability-and-slos.md)** |
| Production / enterprise go-live | **[Enterprise deployment checklist](08-enterprise-deployment-checklist.md)** |
| Disk self-healing (Space Guardian) | **[Space Guardian](../maintainers/06-space-guardian.md)** |
| RAM parking (Memory Guardian) | **[Memory Guardian](../maintainers/07-memory-guardian.md)** |
| Host cleanup inventory / apply | **`GET /v1/admin/cleanup-inventory`**, **`POST /v1/admin/cleanup`** — [HTTP API](../reference/01-http-api-reference.md) |
| Fleet environment provisioning | **[Environments](../operate/environments.md)** · ADR **[Fleet environments](../adr/adr-fleet-environments.md)** |
| Laptop ↔ Granite admin federation | **[Distributed nodes](../operate/distributed-nodes.md)** |
| Git install channel → apt | **[Migrate installations to apt](../operate/migrate-installations-to-apt.md)** |

### Granite host runbooks (operator-specific)

| Topic | Page |
|------|------|
| Fleet upgrade without routine SSH | **[Granite Fleet upgrade (API only)](../operate/granite-fleet-upgrade-only-ssh.md)** |
| Market Studio cutover | **[Granite Market Studio cutover](../operate/granite-market-studio-cutover.md)** |
| Market Studio dev / N-env / edge | **[Dev](../operate/granite-market-studio-dev.md)** · **[Environments](../operate/granite-market-studio-environments.md)** · **[Edge plane](../operate/granite-market-edge-plane.md)** |
| Postgres on Granite | **[Granite Postgres (PG-A)](../operate/granite-postgres-pg-a.md)** |

Release notes (**`CHANGELOG.md`**) complement this section—particularly **`### Host operator`** blocks paired with **`docs/host-operator-steps.json`** and **`scripts/fleet-host-upgrade-hints.sh`** when upgrading bare-metal installs.

**Before:** **[Build 201](../build-201/README.md)** · **After:** **[Reference](../reference/README.md)** for protocol detail
