# Operations runbook

Short procedures for a Fleet host you maintain. Adjust paths for your **`FLEET_DATA_DIR`** and service name.

## Service status

```bash
systemctl --user status forge-fleet.service
# or
systemctl status forge-fleet.service
```

Confirm **`Active: active (running)`** and no restart loop. **`journalctl --user -u forge-fleet.service -n 200`**.

## Caddy (if used)

```bash
systemctl status caddy
caddy validate --config /etc/caddy/Caddyfile   # path may differ
```

Fix DNS/TLS before debugging Fleet JSON errors through the proxy.

## Docker / Podman

```bash
docker version
docker info
```

Runner uses **`FLEET_DOCKER_BIN`** when set. If **`docker: command not found`**, install engine or set the override.

## Version and git alignment

```bash
curl -sS -H "Authorization: Bearer $FLEET_BEARER_TOKEN" http://127.0.0.1:18766/v1/version
```

Compare **`package_semver`**, **`db_schema_version`**, and git fields to what you expect from **`FLEET_GIT_ROOT`**.

## SQLite and data directory

```bash
sqlite3 "$FLEET_DATA_DIR/fleet.sqlite" 'select count(*) from jobs;'
```

If **`jobs_total=0`** but clients claim jobs ran, you may be pointing at a **wrong data dir** or a fresh DB volume.

## Admin snapshot (quick health)

```bash
curl -sS -H "Authorization: Bearer $FLEET_BEARER_TOKEN" \
  "http://127.0.0.1:18766/v1/admin/snapshot" | jq '.meta.sqlite_path, .meta.fleet_data_dir, .jobs_by_status'
```

## Token rotation

1. Stop Fleet (**`systemctl --user stop forge-fleet.service`**).
2. Set a new **`FLEET_BEARER_TOKEN`** in **`forge-fleet.env`** (or unit drop-in).
3. Update any clients (Lenses, certificators, cron **`curl`**).
4. Start Fleet.

## Upgrading host packages

Upgrade **Docker**, **Caddy**, **glibc** on a schedule unrelated to Fleet releases when possible; retest **`POST /v1/jobs`** with a trivial container after Docker upgrades.

## Wrong data directory symptom

**`/admin/`** shows empty job history and **`jobs_total:0`** while operators expect rows—confirm **`FLEET_DATA_DIR`** in the unit matches the volume you think.

## Runbook entries (symptom-first)

Use **[Troubleshooting](04-troubleshooting.md)** for deep ladders; this section captures **fast paths**.

### Fleet service not responding

| | |
| --- | --- |
| **Impact** | No job progress; integrations fail |
| **Severity** | P1 |
| **Fast checks** | `systemctl --user is-active forge-fleet.service` (or system unit); `curl -fsS http://127.0.0.1:18766/v1/version` |
| **Mitigation** | `journalctl --user -u forge-fleet.service -n 200`; verify **`FLEET_DATA_DIR`** mount; restart unit |
| **Validate** | Health + version JSON returns |
| **Prevent** | watchdog + disk alerts |

### Auth failures (**401** / **403**)

| | |
| --- | --- |
| **Impact** | Clients cannot enqueue jobs |
| **Severity** | P1 |
| **Fast checks** | `grep FLEET_BEARER_TOKEN` env file; test **`curl`** with/without header |
| **Mitigation** | Align token across Lenses + Fleet env; confirm bind address vs **`FLEET_ENFORCE_BEARER`** |
| **Validate** | **`POST /v1/jobs`** returns **201** with header |

### Docker unavailable

Follow **Docker / Podman** section above; escalate to host image or **`FLEET_DOCKER_BIN`**.

### Jobs stuck **queued** or **running**

| | |
| --- | --- |
| **Fast checks** | `GET /v1/jobs/{id}` for **`meta.failure`**; runner logs in journal |
| **Mitigation** | **[Troubleshooting](04-troubleshooting.md)**; restart Docker; cancel job if safe |

### Workspace upload rejected

Compare tarball size/profile to **[Workspace upload](../build-201/01-workspace-upload.md)**; inspect **400** JSON **`error`** field.

### Template build fails

Check **`GET /v1/container-templates/status`**; docker buildx present (**[Container templates](../build-201/02-container-templates.md)**).

### Disk full / oversized logs

| | |
| --- | --- |
| **Mitigation** | Prune old jobs if policy allows; expand volume; rotate logs |
| **Prevent** | alarms on **`FLEET_DATA_DIR`** free space |

### Caddy / TLS failure

Validate Caddyfile; fix DNS; **`curl -v https://host/`**.

### Admin static assets broken

Hard-refresh browser; confirm Fleet version matches submodule expectations; reopen **`/admin/`** from loopback to isolate proxy issues.

### SQLite locked or corrupt

Stop Fleet; copy DB for forensics; restore from backup (**[Backup & DR](06-backup-restore-and-disaster-recovery.md)**).

### Remote **`git-self-update`** partial

Read **400** JSON for hand-off commands (**[Upgrade](05-upgrade-release-and-remote-update.md)**); finish on host shell.

## See also

- **[TROUBLESHOOTING.md](04-troubleshooting.md)**  
- **[HOST-BOOTSTRAP.md](../learn-101/03-host-bootstrap.md)**
