# Granite — Market Studio cutover (Fleet API only)

Deploy and migrate Forge Market Studio on Granite **without SSH file operations**.

## Prerequisites

- Fleet GW-1/GW-2 code deployed on Granite (`POST /v1/admin/git-self-update` or [Fleet upgrade SSH exception](granite-fleet-upgrade-only-ssh.md) for the daemon only).
- Local backup: `forge-market/scripts/backup-market-studio.sh` (optionally include broker/raw-sec per manifest flags).
- `FORGE_FLEET_BASE_URL` and `FORGE_FLEET_BEARER_TOKEN` on the operator workstation.
- **forge-migrator** installed locally (`./scripts/start-migrator.sh`) for sandbox/debug cycles — optional when using Market Studio Settings.

## Preferred operator path — Market Studio Settings

1. Launch UI against Granite data plane (operator plane stays local):

   ```bash
   cd forge-market
   ./scripts/start-market-studio.sh --ui-remote
   ```

   Vite proxies `/api` and `/health` to the Fleet app gateway; `/api/operator/*` stays on local `:9792`.

2. Open **Settings → Move data to Granite** — selects corpus/DB/broker/wiki flags, runs local backup, builds a chunked Fleet bundle, and runs Fleet steps in order.

3. After completion, **Test remote data** compares gateway `/health` and `/api/storage/inventory` to the pre-migrate local snapshot.

4. Optional **Remove local data** — separate dialog; typed confirm `DELETE LOCAL MARKET DATA`; never deletes `config/` or `.env.local`.

Operator HTTP surface (local studio-server only):

| Method | Path | Role |
|--------|------|------|
| GET | `/api/operator/hosting` | Fleet/gateway readiness + local inventory |
| POST | `/api/operator/migrations` | Create session |
| POST | `/api/operator/migrations/{id}/start` | Background upload + Fleet steps (`market-prod`) |
| GET | `/api/operator/migrations/{id}` | Poll upload bytes + Fleet step status |
| POST | `/api/operator/migrations/{id}/verify` | Remote smoke vs local snapshot |
| GET | `/api/operator/wipe/preview` | List delete candidates + keep-list |
| POST | `/api/operator/wipe` | Dry-run or delete local `data/` (guarded) |

## API-only cutover sequence (curl / migrator)

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
     -d '{"source_label":"forge-market-local","target_label":"market-prod","meta":{"recipe":"forge-market","app_slug":"forge-market"}}'

   # Upload backup tarball (replace MIGRATION_ID) — prefer chunked upload-session for multi-GB payloads
   curl -sS -X POST "${FORGE_FLEET_BASE_URL}/v1/migrations/MIGRATION_ID/data-bundle/upload-session" \
     -H "Authorization: Bearer ${FORGE_FLEET_BEARER_TOKEN}" \
     -H "Content-Type: application/json" \
     -d '{"sha256":"<64 hex>","total_bytes":N,"chunk_size":67108864}'

   # PUT chunks, POST finalize, then run steps using UUIDs from GET /v1/migrations/MIGRATION_ID
   FLEET_STEP_ID="$(curl -sS "${FORGE_FLEET_BASE_URL}/v1/migrations/MIGRATION_ID" \
     -H "Authorization: Bearer ${FORGE_FLEET_BEARER_TOKEN}" \
     | jq -r '.steps[] | select(.kind=="seed_corpus_volume") | .id')"
   curl -sS -X POST "${FORGE_FLEET_BASE_URL}/v1/migrations/MIGRATION_ID/steps/${FLEET_STEP_ID}/run" \
     -H "Authorization: Bearer ${FORGE_FLEET_BEARER_TOKEN}" \
     -H "Content-Type: application/json" \
     -d '{}'
   ```

3. **Verify**

   ```bash
   curl -sS "${FORGE_FLEET_BASE_URL}/v1/container-services/market-prod" \
     -H "Authorization: Bearer ${FORGE_FLEET_BEARER_TOKEN}"
   curl -sS "${FORGE_FLEET_BASE_URL}/v1/app-gateways/market-studio/health" \
     -H "Authorization: Bearer ${FORGE_FLEET_BEARER_TOKEN}"
   ```

## Rollback (API only)

```bash
curl -sS -X POST "${FORGE_FLEET_BASE_URL}/v1/container-services/market-prod/stop" \
  -H "Authorization: Bearer ${FORGE_FLEET_BEARER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{}'

FLEET_RESTORE_ID="$(curl -sS "${FORGE_FLEET_BASE_URL}/v1/migrations/MIGRATION_ID" \
  -H "Authorization: Bearer ${FORGE_FLEET_BEARER_TOKEN}" \
  | jq -r '.steps[] | select(.kind=="restore_from_bundle") | .id')"
curl -sS -X POST "${FORGE_FLEET_BASE_URL}/v1/migrations/MIGRATION_ID/steps/${FLEET_RESTORE_ID}/run" \
  -H "Authorization: Bearer ${FORGE_FLEET_BEARER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{}'
```

## Forbidden on Granite SSH

- `scp`, `rsync`, manual `tar` extract for Market data
- Manual `docker compose` for Market Studio
- Manual Caddy file edits (use `register_edge_route` — Fleet app gateway, no new tunnel)
