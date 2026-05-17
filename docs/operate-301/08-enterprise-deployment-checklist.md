# Operate 301 — Enterprise deployment checklist

**Audience:** security, platform, and release stakeholders signing off on a Fleet host.  
**Outcome:** explicit **go / no-go** items before exposing Fleet beyond a lab.

## Go / no-go

| # | Item | Owner | Evidence |
| --- | --- | --- | --- |
| 1 | **Bearer + bind policy** matches threat model (**[Security](01-security.md)**) | Security | Config review + **`GET`** probe without token fails as expected |
| 2 | **TLS** terminates at Caddy / LB with valid certs (**[Caddy + systemd](../build-201/03-caddy-systemd.md)**) | Platform | Browser + **`curl`/`openssl s_client`** |
| 3 | **Docker** isolation documented (socket perms, optional rootless/gVisor) | Platform | Runbook entry |
| 4 | **Backups** of `fleet.sqlite` + `etc/` scheduled (**[Backup & DR](06-backup-restore-and-disaster-recovery.md)**) | Ops | Restore drill ticket |
| 5 | **Remote update** path understood (**[Upgrade](05-upgrade-release-and-remote-update.md)**) | Release | Dry-run on staging |
| 6 | **Observability** hooks in place (**[Observability](07-observability-and-slos.md)**) | Ops | Dashboard screenshot or alert definition |

## Operational readiness

- On-call knows **symptom → runbook** mapping (**[Troubleshooting](04-troubleshooting.md)**).
- **`CHANGELOG`** host-operator notes for the target version are applied.

## Rollback tested

- You can reinstall **N−1** bits or restore **N** data dir from backup per policy.

## Post-deploy smoke

1. **`GET /v1/version`**, **`GET /v1/health`**.  
2. **`POST /v1/jobs`** with **`kind: docker_argv`** trivial container — **HTTP 201**.  
3. **`GET /v1/jobs/{id}`** reaches terminal **`completed`**.

## Related

- **[Security](01-security.md)**  
- **[Operations runbook](02-operations-runbook.md)**
