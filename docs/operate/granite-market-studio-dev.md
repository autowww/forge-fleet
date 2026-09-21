# Market Studio DEV stack on Granite

Second compose stack for delivery-pipeline DEV/PROD split.

**Generic provisioning:** use Fleet `POST /v1/environments` or Lenses **Publish → Environments** — see [environments.md](environments.md).

## Layout

| Item | PROD | DEV |
|------|------|-----|
| Compose project | `forge-market-studio` | `forge-market-studio-dev` |
| App port | 19792 | 19793 |
| Postgres port | 15432 | 15433 |
| Gateway slug | `market-studio` | `market-studio-dev` |
| Volumes | `forge_market_studio_*` | `forge_market_studio_dev_*` |

## Register DEV gateway

```bash
./scripts/register-market-studio-dev-gateway.sh
```

Requires `FORGE_FLEET_BASE_URL` and `FORGE_FLEET_BEARER_TOKEN`.

## DEV rollout

```bash
FORGE_MARKET_ENV=dev ./scripts/rollout-forge-market-studio.sh
```

## Digest promotion (no rebuild)

```bash
curl -fsS -X POST "$FORGE_FLEET_BASE_URL/v1/admin/forge-market-studio-rollout" \
  -H "Authorization: Bearer $FORGE_FLEET_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"forge_market_env":"prod","forge_market_skip_build":true,"forge_market_app_image":"forge-market-app@sha256:..."}'
```

## App deployment status

```bash
curl -fsS "$FORGE_FLEET_BASE_URL/v1/admin/app-deployments/market-studio-dev" \
  -H "Authorization: Bearer $FORGE_FLEET_BEARER_TOKEN"
```

## Rollout concurrency (per environment)

Fleet serializes mutating rollouts **per `container_service_id`** (`market-studio` vs `market-studio-dev`), not per host.

- A second rollout to the **same** environment while one is active returns **HTTP 409** `rollout_in_progress` from `POST /v1/flows/submit` (infra flows) or `POST /v1/admin/forge-market-studio-rollout`.
- Rollouts to **different** environments on the same host may run in parallel (separate compose dirs, ports, volumes).
- Poll progress: `GET /v1/managed-services/market-studio-dev/maintenance-status` and `…/rollout-log`.
- Lenses Studio (Delivery pipeline, Infra flows) surfaces 409 with a link to the active Fleet job when `job_id` is returned.

See also [granite-market-studio-cutover.md](granite-market-studio-cutover.md).

If Fleet shows `FORGE_MARKET_DOCKERFILE is missing`, the compose `.env` was copied from `.env.example` without a rollout. Run `POST /v1/admin/forge-market-studio-rollout` (prod and/or `forge_market_env: dev`). The script writes the absolute Dockerfile path and starts the stack. Compose also falls back to `forge-market/Dockerfile` when the variable is empty so `docker compose ps` still works.
