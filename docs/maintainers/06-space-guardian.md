# Space Guardian — self-healing disk on Fleet hosts

Space Guardian is the Fleet daemon loop that reclaims safe disk on Granite without SSH.

## Tiers

| Tier | Trigger | Actions |
|------|---------|---------|
| 0 | Every `FLEET_SPACE_INTERVAL_S` (default 6h) | Rollout backup GC, migration scratch, job-workspaces >7d, Docker builder cache, dangling images, telemetry retention, app GC (`aggressive=false`) |
| 1 | Disk pressure (`free < 15%` or `< 40 GB` on `/` / Docker / Fleet data) | Unused images `-a` >72h, legacy backup roots, quarantined volumes past TTL, app GC (`aggressive=true`) |
| 2 | Manual only | Containers, env delete, registered env volumes, `VACUUM FULL` |

## API

- `GET /v1/admin/space` — pressure, guardian status, quarantine registry, last/next run
- `POST /v1/admin/space/run` — body: `tier` (0|1), `dry_run` (default true)
- `POST /v1/admin/space/approve` — body: `volume_name` — operator approves orphan volume deletion
- `GET /v1/admin/cleanup-inventory` / `POST /v1/admin/cleanup` — per-target cleanup (Studio Storage page)

## Orphan volumes

Volumes are orphans when they are not mounted by any container and not listed in a Fleet environment record.

1. **candidate** — first seen
2. **quarantined** — seen again on a later scan
3. **approval_required** — past TTL but larger than `FLEET_VOLUME_SNAPSHOT_MAX_GB` (default 10 GB)
4. **approved_for_delete** — operator approved via `/v1/admin/space/approve`
5. **deleted** — removed after snapshot tarball under `data_dir/space/volume-snapshots/`

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `FLEET_SPACE_GUARDIAN` | `1` | Enable scheduler |
| `FLEET_SPACE_INTERVAL_S` | `21600` | Tier 0 interval (6h) |
| `FLEET_SPACE_PRESSURE_FREE_PCT` | `15` | Pressure if free % below |
| `FLEET_SPACE_PRESSURE_FREE_GB` | `40` | Pressure if free GB below |
| `FLEET_VOLUME_QUARANTINE_DAYS` | `14` | Days before quarantined volume eligible |
| `FLEET_VOLUME_SNAPSHOT_MAX_GB` | `10` | Snapshot before delete; above → approval |
| `FLEET_LEGACY_BACKUP_ROOTS` | `:`-separated paths | Tier 1 legacy backup GC (also scans `~/forge-market-backups`) |
| `FLEET_VOLUME_ALLOWLIST` | comma names | Never treat as orphan |

## App GC (forge-market container)

`GET/POST /api/maintenance/gc` on market-app (Fleet calls via app gateway during Tier 0/1).

Targets: stale harvest job files, wiki workspaces, broker snapshots, Postgres `VACUUM (ANALYZE)` on high dead-tuple tables when `aggressive=true`.

**Fan-out budget.** The app inventory walks the whole corpus inside the container (minutes on Granite), so Fleet only asks for it from `GET /v1/admin/space` and `GET /v1/admin/cleanup-inventory`, caches each answer per environment for `FLEET_APP_GC_CACHE_TTL_SEC` (default 600 s) and bounds the request at `FLEET_APP_GC_TIMEOUT_SEC` (default 15 s). `GET /v1/admin/snapshot` (`meta.space`) never calls the app — it is polled every ~20 s by dock collectors and studios, and before this budget every poll started a corpus walk on market-app until all its HTTP workers were pinned (Granite prod, 2026-10-07).

## Verification

```bash
curl -fsS -H "Authorization: Bearer $FORGE_FLEET_BEARER_TOKEN" \
  "$FORGE_FLEET_BASE_URL/v1/admin/space" | jq .

curl -fsS -X POST -H "Authorization: Bearer $FORGE_FLEET_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tier":0,"dry_run":true}' \
  "$FORGE_FLEET_BASE_URL/v1/admin/space/run" | jq .
```

## Rollback

- Disable: `FLEET_SPACE_GUARDIAN=0` and restart `forge-fleet.service`
- Restore volume: create new volume from `data_dir/space/volume-snapshots/<name>.tar` via `volume_ops.volume_cold_copy`
