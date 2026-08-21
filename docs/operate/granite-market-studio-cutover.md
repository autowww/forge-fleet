# Granite — Market Studio cutover (Fleet API only)

Deploy and migrate Forge Market Studio on Granite **without SSH file operations**.

## Prerequisites

- Fleet GW-1/GW-2 code deployed on Granite (`POST /v1/admin/git-self-update` or [Fleet upgrade SSH exception](granite-fleet-upgrade-only-ssh.md) for the daemon only).
- Local backup: `forge-market/scripts/backup-market-studio.sh` (optionally include broker/raw-sec per manifest flags).
- `FORGE_FLEET_BASE_URL` and `FORGE_FLEET_BEARER_TOKEN` on the operator workstation.
- **forge-migrator** installed locally (`./scripts/start-migrator.sh`).

## API-only cutover sequence

1. **Rollout compose stack registration** (once per Fleet data-dir):

   ```bash
   curl -sS -X POST "${FORGE_FLEET_BASE_URL}/v1/admin/forge-market-studio-rollout" \
     -H "Authorization: Bearer ${FORGE_FLEET_BEARER_TOKEN}" \
     -H "Content-Type: application/json" \
     -d '{"sync": true}'
   ```

2. **Run migrator recipe** `forge-market` in the Electron wizard — or equivalent curl sequence:

   ```bash
   # Create migration session
   curl -sS -X POST "${FORGE_FLEET_BASE_URL}/v1/migrations" \
     -H "Authorization: Bearer ${FORGE_FLEET_BEARER_TOKEN}" \
     -H "Content-Type: application/json" \
     -d '{"recipe_id":"forge-market","target_service_id":"market-prod"}'

   # Upload backup tarball (replace MIGRATION_ID)
   curl -sS -X PUT "${FORGE_FLEET_BASE_URL}/v1/migrations/MIGRATION_ID/data-bundle" \
     -H "Authorization: Bearer ${FORGE_FLEET_BEARER_TOKEN}" \
     -H "Content-Type: application/gzip" \
     --data-binary @forge-market-backup.tar.gz

   # Run steps in order (build_image, seed_corpus, migrate_db, deploy_service, register_edge_route, verify)
   curl -sS -X POST "${FORGE_FLEET_BASE_URL}/v1/migrations/MIGRATION_ID/steps/seed_corpus/run" \
     -H "Authorization: Bearer ${FORGE_FLEET_BEARER_TOKEN}" \
     -H "Content-Type: application/json" \
     -d '{}'
   ```

3. **Verify**

   ```bash
   curl -sS "${FORGE_FLEET_BASE_URL}/v1/container-services/market-prod" \
     -H "Authorization: Bearer ${FORGE_FLEET_BEARER_TOKEN}"
   curl -sS "https://GRANITE_HOST/market-studio/health" \
     -H "Authorization: Bearer ${FORGE_MARKET_STUDIO_API_TOKEN}"
   ```

## Rollback (API only)

```bash
curl -sS -X POST "${FORGE_FLEET_BASE_URL}/v1/container-services/market-prod/stop" \
  -H "Authorization: Bearer ${FORGE_FLEET_BEARER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{}'

curl -sS -X POST "${FORGE_FLEET_BASE_URL}/v1/migrations/MIGRATION_ID/steps/restore_from_bundle/run" \
  -H "Authorization: Bearer ${FORGE_FLEET_BEARER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{}'
```

## Forbidden on Granite SSH

- `scp`, `rsync`, manual `tar` extract for Market data
- Manual `docker compose` for Market Studio
- Manual Caddy file edits (use `register_edge_route` migration step)
