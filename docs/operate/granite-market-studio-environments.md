# Granite Market Studio — N environments

Fleet parameterizes Market Studio beyond prod/dev using `fleet_server/market_studio_rollout_env.py` and `env_templates.py`.

## Provision clean install

```bash
POST /v1/environments
{
  "template_id": "forge_market_studio",
  "app_id": "forge-market-studio",
  "env_id": "clean",
  "seed": "clean"
}
```

Or rollout after compose dir exists:

```bash
POST /v1/admin/forge-market-studio-rollout
{"forge_market_env":"clean"}
```

## Port allocation

| env_id | app | postgres |
|--------|-----|----------|
| prod | 19792 | 15432 |
| dev | 19793 | 15433 |
| clean | 19794 | 15434 |

Unknown env_ids must use `environments.allocate_ports()` — never `prod + 1` (collides with dev).

## Compose notes

- `compose.granite.yaml` uses `${FORGE_MARKET_APPDATA_VOLUME}` for external appdata (env-scoped).
- `clear_hosted_data_plane_pref` enumerates all known appdata volumes including clean.

## Rollout concurrency

Only one mutating rollout/rollback/replicate may run per **`container_service_id`** at a time (`market-studio`, `market-studio-dev`, `market-studio-clean`, …). Submit paths return **409** `rollout_in_progress` when the slot is held; use `GET /v1/managed-services/{service_id}/maintenance-status` to inspect the active rollout. Different environments on the same Fleet host are independent slots.
