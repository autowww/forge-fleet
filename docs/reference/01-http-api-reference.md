# Fleet HTTP API reference (v1)

Canonical list of HTTP routes exposed by **`fleet_server`**. **OpenAPI 3.1** (stable **`operationId`** values for SDKs) lives in [`schemas/openapi.json`](../schemas/openapi.json) — regenerate metadata with **`python3 scripts/apply_openapi_contract.py`** when routes change but summaries already exist. **JSON Schemas:** [`Schemas & OpenAPI`](02-schemas-and-openapi.md). For install and operations, see the [repository README](../../README.md). For narrative context, see **[What is Fleet?](../learn-101/01-what-is-fleet.md)**. For **`curl`** snippets, see **[Examples](../build-201/05-examples-and-recipes.md)**.

Feature docs (details beyond this table): [CONTAINER-TEMPLATES.md](../build-201/02-container-templates.md), [WORKSPACE_UPLOAD.md](../build-201/01-workspace-upload.md).

## Auth column

| Value | Meaning |
|-------|---------|
| **none** | No bearer; admin HTML and static under `/admin/`. |
| **worker** | `X-Workspace-Worker-Token` (per job). Not `Authorization`. |
| **bearer** | `Authorization: Bearer <FLEET_BEARER_TOKEN>` when the server’s auth policy requires it. See **Authentication** below. |

## Routes

| Method | Path | Auth | Notes |
|--------|------|------|--------|
| GET | `/admin` | none | 302 redirect to `/admin/` |
| GET | `/admin/` | none | Admin dashboard HTML (kitchensink theme; polls snapshot). |
| GET | `/admin/theme.css` | none | Legacy minimal CSS. |
| GET | `/admin/ks/{path}` | none | Kitchensink `css/` and `js/` assets only. |
| GET | `/admin/static/{path}` | none | Packaged static (e.g. `gpu-logos/*.png`). |
| GET | `/v1/jobs/{id}/workspace-worker-bundle` | worker | Returns `argv` / `cwd` from `meta.workspace_worker_bundle`. |
| POST | `/v1/jobs/{id}/workspace-worker-progress` | worker | Merge JSON progress into job. |
| POST | `/v1/jobs/{id}/workspace-worker-complete` | worker | Final JSON result for worker bridge. |
| GET | `/v1/version` | bearer | Semver, DB schema, template library, optional git SHA. |
| GET | `/v1/templates` | bearer | Container template catalog (`host_cpu_probe`, etc.). |
| GET | `/v1/health` | bearer | `service: forge-fleet`, host CPU/mem/load, energy ledger; may sample telemetry. |
| GET | `/v1/admin/snapshot` | bearer | Jobs, integrations, host, **`jobs_recent`** paging (`jobs_limit`, `jobs_offset`), thermal advisory, self-update meta. |
| GET | `/v1/cooldown-summary` | bearer | Query **`period=`** required (same values as **`/v1/telemetry`**). |
| GET | `/v1/telemetry` | bearer | Query **`period=`** required; optional **`limit`** (default large). |
| GET | `/v1/container-templates/status` | bearer | Build cache JSON + in-progress flag. |
| GET | `/v1/container-templates` | bearer | `requirement_templates.json` + filesystem paths. |
| GET | `/v1/container-templates/resolve` | bearer | Query **`requirements`**; optional build-if-missing — see CONTAINER-TEMPLATES. |
| GET | `/v1/container-types` | bearer | `types.json` + materialized capabilities + `paths`. |
| GET | `/v1/container-services` | bearer | All `etc/services/*.json` + forge_llm compose status. |
| GET | `/v1/container-services/{id}` | bearer | One service + paths. |
| GET | `/v1/services/forge-llm` | bearer | Legacy aggregate for primary `forge_llm` id. |
| GET | `/v1/jobs/{id}` | bearer | Job row; secrets in `meta` redacted in output. |
| POST | `/v1/cooldown-events` | bearer | **`duration_s`** plus optional **`kind`**, **`meta`**. |
| POST | `/v1/jobs` | bearer | **`kind: docker_argv`**; optional workspace / template fields — see WORKSPACE_UPLOAD. |
| PUT | `/v1/jobs/{id}/workspace` | bearer | Raw gzip tarball; optional **`X-Workspace-Archive-Sha256`**. |
| POST | `/v1/jobs/{id}/cancel` | bearer | Best-effort cancel. |
| POST | `/v1/containers/dispose` | bearer | Body **`container_id`** — `docker rm -f`. |
| POST | `/v1/admin/test-fleet` | bearer | Optional **`count`** — enqueue `host_cpu_probe` jobs. |
| POST | `/v1/admin/git-self-update` | bearer | Git pull + install hooks; system install may return **400** with instructions. |
| POST | `/v1/container-services` | bearer | Create managed service (`type_id`, `compose_root`, …). |
| PUT | `/v1/container-services/{id}` | bearer | Update service record. |
| DELETE | `/v1/container-services/{id}` | bearer | Delete; **409** if forge_llm still running. |
| POST | `/v1/container-services/{id}/start` | bearer | **`docker compose up`** for **forge_llm** services. |
| POST | `/v1/container-services/{id}/stop` | bearer | **`docker compose down`**. |
| POST | `/v1/container-types` | bearer | Append one **`types[]` row**. |
| PUT | `/v1/container-types` | bearer | Replace full **`types.json`**. |
| PUT | `/v1/container-types/{id}` | bearer | Update one row by id. |
| DELETE | `/v1/container-types/{id}` | bearer | Delete; **409** if reserved or referenced. |
| POST | `/v1/container-templates/build` | bearer | Body **`requirement_ids`** / **`requirements`** list. |
| PUT | `/v1/container-templates` | bearer | Replace **`requirement_templates.json`**. |
| PUT | `/v1/container-templates/{id}/package` | bearer | Binary template package; query **`title`**, **`notes`**, **`replace`**. |
| POST | `/v1/services/forge-llm/start` | bearer | Legacy — start primary forge_llm. |
| POST | `/v1/services/forge-llm/stop` | bearer | Legacy — stop primary forge_llm. |

### Response and query details

- **`GET /v1/health`** — CPU % from **`/proc/stat`**; memory from **`/proc/meminfo`**; **energy_ledger_kwh** cumulative on this DB (RAPL + GPU draw × time). See prior handbook text in git history for extended field lists if needed.
- **`GET /v1/telemetry`** — Periods and aliases match **[EXAMPLES.md](../build-201/05-examples-and-recipes.md)**; retention/prune via **`FLEET_TELEMETRY_RETENTION_DAYS`**, sample interval **`FLEET_TELEMETRY_INTERVAL_S`**.
- **`GET /v1/admin/snapshot`** — Integrations include **`forge_console_url`**, **`suggested_forge_llm_compose_root`**, **`container_layout`**, **`orchestration`**, Forge LLM service rows, **`cooldown_summary`** presets, **`self_update`**.

## Authentication

- **`FLEET_BEARER_TOKEN`** set and **`--host`** is **not** loopback-only: `/v1/...` requires `Authorization: Bearer` except where **worker** auth applies.
- **Loopback-only bind** with a token configured: bearer optional for same-machine callers unless **`FLEET_ENFORCE_BEARER=1`**.
- **No token** in env: requests accepted on any interface (development only).

## Docker workloads: live host metrics (`GET /v1/health`)

When **`FLEET_INJECT_HOST_METRICS_ENV_IN_DOCKER`** is truthy **and** **`FLEET_HOST_METRICS_BASE_URL`** is set, the runner injects **`FLEET_HOST_METRICS_URL`** and **`FLEET_HOST_METRICS_TOKEN`** (copy of bearer when set) into `docker_argv` jobs. See **[EXAMPLES.md](../build-201/05-examples-and-recipes.md)** and README — **this exposes the admin token inside containers** when enabled.

## Admin self-update (`POST /v1/admin/git-self-update`)

Documented in the [README](../../README.md): **`FLEET_GIT_ROOT`**, **`FLEET_SELF_UPDATE_POST_GIT_COMMAND`**, system-install **400** path with **`system_root_install_command`**.

## See also

- **[EXAMPLES.md](../build-201/05-examples-and-recipes.md)** — `curl` recipes.
- **[SCHEMAS.md](02-schemas-and-openapi.md)** — machine-readable schemas and **`/schemas/`** on the public site.
