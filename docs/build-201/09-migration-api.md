# Migration API (`/v1/migrations`)

Fleet-controlled **data bundle upload** and **step jobs** for Granite cutover — no SSH `scp`/`rsync` for Market Studio payloads (see [Granite operator boundary](../design/granite-operator-boundary.md)).

## Flow

1. **`POST /v1/migrations`** — create a migration session with default step kinds (`seed_corpus_volume`, `migrate_db`, `build_image`, `deploy_service`, `register_edge_route`). Optional body field `include_restore_step: true` adds `restore_from_bundle` for rollback recipes.

2. **`PUT /v1/migrations/{id}/data-bundle`** — upload a gzip tarball (same safety limits as workspace upload, **`migration_bundle`** profile: up to **2 GiB** uncompressed). Optional header **`X-Migration-Bundle-Sha256`** must match the body digest when set. Default upload cap **500 MiB** (`FLEET_MIGRATION_BUNDLE_UPLOAD_MAX_BYTES`).

3. **`GET /v1/migrations/{id}`** — session status, **`bytes_transferred`**, bundle digests, parsed manifest flags, and per-step state.

4. **`POST /v1/migrations/{id}/steps/{step_id}/run`** — queue a `docker_argv` job using stub scripts under `fleet_server/migration_stubs/` (GW-2); real Market tooling replaces stubs in later waves.

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
| `seed_corpus_volume` | Copy corpus/wiki trees from bundle into named Docker volumes |
| `migrate_db` | SQLite → Postgres migration using bundle SQL dumps |
| `build_image` | Build or pull application image on Granite |
| `deploy_service` | Register/start managed compose service |
| `register_edge_route` | Write Caddy snippet and reload edge proxy |
| `restore_from_bundle` | Rollback restore from the same bundle (optional step) |

## Environment

| Variable | Default | Meaning |
|----------|---------|---------|
| `FLEET_MIGRATION_BUNDLE_UPLOAD_MAX_BYTES` | `524288000` (500 MiB) | Max compressed upload size |
| `FLEET_MIGRATION_STUB_IMAGE` | `alpine:3.20` | Image for GW-2 stub step containers |

## Related

- [Workspace upload](01-workspace-upload.md) — per-job tarball pattern reused for bundles
- [HTTP API reference](../reference/01-http-api-reference.md)
- Requirements **R04**, **R05**, **R13**, **R21**, **R22**, **R24** in the PDCA ledger
