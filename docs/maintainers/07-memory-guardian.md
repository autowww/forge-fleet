# Memory Guardian — idle RAM parking (Fleet daemon)

Memory Guardian runs inside **`fleet-server`** (same process as Space Guardian). It classifies managed compose services and optional cold targets (host Ollama via systemd user unit), records idle time from gateway stats and wake events, and can stop warm/cold workloads when policy allows.

## Pressure signal

Use host **`MemAvailable`** (`/proc/meminfo`), not Docker cgroup memory percent. Docker `MemUsage` includes reclaimable page cache.

## Policy file

`{fleet_data_dir}/etc/capacity-policy.json` — also holds **`space.enabled`** override for the disk loop. When `space.enabled` is `null`, disk scheduling follows **`FLEET_SPACE_GUARDIAN`**.

Defaults:

- Memory loop on; **`apply_stops`** **false** (observe-only until operator enables in **Capacity** tab).
- Free RAM floor **16 GiB**; cold idle **2h**; warm idle **6h**.
- Pinned: `default`, `market-studio`. Warm: `market-studio-dev`. Cold: `ollama.service` (systemd user), ComfyUI compose service name when present.

## Tiers

| Tier | Trigger | Behavior |
|------|---------|----------|
| 0 | Scheduled (`FLEET_MEMORY_INTERVAL_S`, default 3600s) | Dry-run plan only |
| 1 | Scheduled when `apply_stops` true, or manual | Stop idle warm (only under RAM floor) and idle cold targets |
| 2 | Manual API with `service_id` | Operator-confirmed stop (UI should require confirm) |

Skips when disk guardian skips: draining, upgrade, rollout slot held; plus `memory.enabled` false.

## API

- `GET /v1/admin/memory` — pressure, services, cold targets, plan (cached ~15s; not called from snapshot).
- `POST /v1/admin/memory/run` — body: `tier`, `dry_run` (default true), optional `service_id` for tier 2.
- `POST /v1/admin/memory/ensure-running` — body: `target_id` (default `host-ollama`), `wait_sec`.
- `GET /v1/admin/capacity/policy` — full policy document.
- `PUT /v1/admin/capacity/policy` — merge patch for `space` and `memory` blocks.

Snapshot: `meta.memory` compact summary (like `meta.space`).

## Wake path

**forge-gateway** (`deploy/forge-llm-control-plane`) calls `POST /v1/admin/memory/ensure-running` on Ollama connection failure when **`FLEET_WAKE_BEARER_TOKEN`** (or **`FORGE_API_TOKEN`**) is set. **`FLEET_WAKE_BASE_URL`** defaults to `http://host.docker.internal:18766`.

## UI

Fleet admin **`/admin/`** → **Capacity** tab: disk (Space Guardian) + memory + policy editor.

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `FLEET_MEMORY_GUARDIAN` | `1` | Start memory scheduler thread |
| `FLEET_MEMORY_INTERVAL_S` | `3600` | Scheduled pass interval |

Disk variables remain in [06-space-guardian.md](06-space-guardian.md).

## Ship

Feature ships in **`forge-fleet`** / **`forge-fleet-user`** apt packages (`build-debs.sh` rsyncs `fleet_server/` and `deploy/forge-llm-control-plane/`). Granite upgrades via apt CDN + `POST /v1/admin/upgrade`.

## Verification

```bash
curl -fsS -H "Authorization: Bearer $FORGE_FLEET_BEARER_TOKEN" \
  "$FORGE_FLEET_BASE_URL/v1/admin/memory" | jq .

curl -fsS -X POST -H "Authorization: Bearer $FORGE_FLEET_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tier":0,"dry_run":true}' \
  "$FORGE_FLEET_BASE_URL/v1/admin/memory/run" | jq .
```
