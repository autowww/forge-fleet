# Migration API (`/v1/migrations`)

Fleet-controlled **data bundle upload** and **step jobs** for Granite cutover — no SSH `scp`/`rsync` for Market Studio payloads (see [Granite operator boundary](../design/granite-operator-boundary.md)).

## Flow

1. **`POST /v1/migrations`** — create a migration session with default step kinds (`seed_corpus_volume`, `migrate_db`, `build_image`, `deploy_service`, `register_edge_route`). Optional body field `include_restore_step: true` adds `restore_from_bundle` for rollback recipes.

2. **`PUT /v1/migrations/{id}/data-bundle`** — upload a gzip tarball in one request (legacy/small bundles). Optional header **`X-Migration-Bundle-Sha256`**.

   **Chunked upload (recommended through Cloudflare, 64 MiB chunks):**

   1. **`POST /v1/migrations/{id}/data-bundle/upload-session`** — body `{ "sha256", "total_bytes", "chunk_size"? }` (default chunk size **64 MiB**).
   2. **`PUT /v1/migrations/{id}/data-bundle/chunks/{index}`** — upload each chunk (`index` from `0` .. `chunk_count-1`).
   3. **`POST /v1/migrations/{id}/data-bundle/finalize`** — Fleet assembles chunks, verifies digest, extracts bundle.

3. **`GET /v1/migrations/{id}`** — session status, **`bytes_transferred`**, bundle digests, parsed manifest flags, and per-step state.

4. **`POST /v1/migrations/{id}/steps/{step_id}/run`** — queue a `docker_argv` job. Step argv is built from **recipe meta** (image, migrate command, data volume, compose root). Fleet does not hard-code application tool paths.

5. **`POST /v1/migrations/{id}/cancel`** — cancel pending steps and running linked jobs.

## Bundle manifest

Extracted trees may include **`.forge_migration_manifest.json`** (schema version `1`):

| Field | Meaning |
|-------|---------|
| `flags.corpus` | Corpus / large file tree present |
| `flags.raw_sec` | Raw SEC store payload |
| `flags.broker` | `broker.db` payload |
| `flags.wiki` | Wiki workspace payload |
| `inventory_bytes` | Optional total inventory hint for ops dashboards |

After upload, Fleet stores the manifest on the session and may **skip** steps that are not needed (for example `migrate_db` when neither `raw_sec` nor `broker` is set).

## Step kinds

| Kind | Purpose |
|------|---------|
| `seed_corpus_volume` | Copy bundle `data/` (or bundle root) into the recipe `data_volume` |
| `migrate_db` | Run recipe `migrate_argv` in recipe `app_image` with bundle + data volume mounted; DSN from `database_url_env` / compose `.env` |
| `build_image` | Build or pull application image on Granite |
| `deploy_service` | `docker compose up -d` using recipe `compose_root` + `compose_files` |
| `register_edge_route` | Register a Fleet **app gateway** on the existing Fleet hostname (`/v1/app-gateways/<service_id>/…`). Does **not** create a Cloudflare tunnel or Caddy snippet. If recipe `app_bearer_env` is set and compose `.env` is empty, Fleet generates a token, writes it (mode 0600), and `deploy_service` force-recreates the compose service so the app process sees it. |
| `restore_from_bundle` | Rollback restore from the same bundle (optional step) |

## Environment

| Variable | Default | Meaning |
|----------|---------|---------|
| `FLEET_MIGRATION_BUNDLE_UPLOAD_MAX_BYTES` | `524288000` (500 MiB) | Global max assembled bundle size when no per-app cap applies |
| `FLEET_MIGRATION_BUNDLE_MAX_BYTES_BY_APP` | — | JSON map `{"forge-market": 536870912000, …}` overriding built-in per-app caps |
| `FLEET_MIGRATION_BUNDLE_MAX_BYTES_<APP>` | — | Per-app override; slug from suffix (`FORGE_MARKET` → `forge-market`) |
| Built-in `forge-market` cap | `536870912000` (500 GiB) | Used when meta/recipe/source identifies forge-market and no env override |
| `FLEET_MIGRATION_CHUNK_SIZE_BYTES` | `67108864` (64 MiB) | Default **per HTTP chunk** for chunked upload (unchanged) |
| `FLEET_MIGRATION_APP_IMAGE` | — | Optional default app image if recipe meta omits `app_image` |
| `FLEET_MIGRATION_DATABASE_URL` | — | Optional DSN if recipe meta / compose `.env` omit it |

| `FLEET_MIGRATION_BUNDLE_MAX_UNCOMPRESSED_BYTES` | `2147483648` (2 GiB) | Global max **uncompressed** extract size when no per-app cap applies |
| `FLEET_MIGRATION_BUNDLE_MAX_UNCOMPRESSED_BYTES_BY_APP` | — | JSON map of per-app uncompressed extract caps |
| `FLEET_MIGRATION_BUNDLE_MAX_UNCOMPRESSED_BYTES_<APP>` | — | Per-app uncompressed override (`FORGE_MARKET` → `forge-market`) |
| Built-in `forge-market` uncompressed cap | `536870912000` (500 GiB) | Matches the upload cap so a full local Market tree can extract on Granite |
| `FLEET_MIGRATION_BUNDLE_MAX_FILES` | `200000` | Global max files in an extracted bundle |
| Built-in `forge-market` file cap | `5000000` | Higher than the generic workspace profile |

`GET /v1/migrations/{id}` includes `bundle_upload_max_bytes`, `bundle_uncompressed_max_bytes`, and `bundle_max_files` for the resolved app.

Extract failures return HTTP 400 `{ "ok": false, "error": "extract_failed", "detail": "<token>", "recovery_code": "<token>" }` so Migrator can show a reason-specific recovery plan. Chunked finalize streams chunks to a temp file and extracts from disk (it does not join the archive in RAM).

**Note:** 64 MiB is the transfer chunk size through Cloudflare, not the total bundle ceiling. Forge Market migrations may assemble and extract bundles up to **500 GiB** by default.

## Related

- [Workspace upload](01-workspace-upload.md) — per-job tarball pattern reused for bundles
- [HTTP API reference](../reference/01-http-api-reference.md)
- Requirements **R04**, **R05**, **R13**, **R21**, **R22**, **R24** in the PDCA ledger
