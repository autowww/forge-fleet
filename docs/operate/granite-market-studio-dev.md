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

See also [granite-market-studio-cutover.md](granite-market-studio-cutover.md).
