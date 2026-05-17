# Architecture

Forge Fleet is a **Python** **BaseHTTPRequestHandler** server (`fleet_server/main.py`) fronting a **SQLite** job store, a **Docker/Podman-invoking** runner, optional **workspace extraction**, **requirement-template** image builds, and **managed compose** services. This page is a maintainers’ map, not a protocol spec (use [HTTP API reference](../reference/01-http-api-reference.md) and [schemas/openapi.json](../schemas/openapi.json) for contracts).

## Request dispatch

1. Parse **`path`** from **`urlparse(self.path).path`**.
2. **Admin and static** (`/admin`, `/admin/ks/*`, `/admin/static/*`) are served without JSON bearer checks.
3. **Workspace-worker** routes validate **`X-Workspace-Worker-Token`** against SQLite before touching job rows.
4. All other **`/v1/*`** routes go through **`_auth_ok()`** (bearer vs loopback policy).
5. Unmatched routes return **404** JSON.

```blueprint-diagram-ascii
key: linear
alt: Dispatch path inside fleet_server
caption: Parsed HTTP path picks admin static, workspace worker, or bearer-gated v1 handler.
Request path -> matcher -> auth gate or static -> handler -> SQLite or Docker
```

## Persistence (SQLite)

- Database file: **`{FLEET_DATA_DIR}/fleet.sqlite`** (configurable).
- Primary entities: **jobs** (status, argv, meta, stdout/stderr, exit, worker bridge fields), **telemetry** samples, **cooldown** events, **version** row.
- Schema migrations run when the store is opened (**`store.py`**).

## Job lifecycle (simplified)

1. **`POST /v1/jobs`** inserts a **`queued`** row; unless **`meta.workspace_upload_required`**, the runner is spawned immediately.
2. If workspace upload is required, state stays **`queued`** until **`PUT .../workspace`** marks **`workspace_state`** **`ready`**, then **`runner.spawn`** runs.
3. Runner executes **`docker_argv`** (or equivalent) and streams output back into SQLite.
4. Terminal states: **`completed`**, **`failed`**, **`cancelled`**.

## Layout on disk (`FLEET_DATA_DIR`)

- **`etc/containers/types.json`** — container type catalog.
- **`etc/containers/requirement_templates.json`** — requirement definitions for template images.
- **`etc/containers/build_cache.json`** — built image metadata keyed by fingerprint.
- **`etc/services/*.json`** — managed compose service records.
- **`job-workspaces/<job_id>/`** — extracted workspace trees when used.

## Docker and Podman

The runner resolves a **`docker`** CLI (override **`FLEET_DOCKER_BIN`**) and constructs **`argv`** from job rows. Template code may **`docker build`** / **`pull`** when resolving images.

## Telemetry

A sampler can record `{host, orchestration}` snapshots on an interval (**`FLEET_TELEMETRY_INTERVAL_S`**), subject to retention pruning (**`FLEET_TELEMETRY_RETENTION_DAYS`**). Admin snapshot and **`GET /v1/telemetry`** read this store.

## Managed Forge LLM services

**`etc/services/`** JSON files describe **`forge_llm`** (and other manageable types). **`docker compose`** is used for start/stop; status is surfaced in **`GET /v1/container-services`**.

## Self-update

**`POST /v1/admin/git-self-update`** shells out to git + optional install scripts (**`self_update.py`**), differentiating user install trees from system **`/opt`** installs.

## See also

- **[SECURITY.md](01-security.md)** — trust boundaries  
- **[CONFIGURATION.md](../reference/03-configuration-and-env.md)** — environment variables
