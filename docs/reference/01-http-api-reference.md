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
| GET | `/v1/health` | public (minimal) / bearer (full) | Anonymous: `{ok, service, ready}` only (no telemetry write). Bearer or loopback admin: full host metrics, version, energy ledger. |
| POST | `/v1/auth/session` | bearer | Mint signed session (`session_id`, `session_secret`, scopes). Use `X-Fleet-Session` + `X-Fleet-Sig` on later calls. |
| GET | `/v1/auth/sessions` | admin | List active sessions. |
| DELETE | `/v1/auth/session/{id}` | admin | Revoke session. |
| GET | `/v1/host/profile` | `read:profile` | Hardware snapshot, Fleet mark (`benchmark`), Market Studio benchmark (`fmsbench`, separate file), 5m rollup history (`period=1h\|24h\|7d`). |
| POST | `/v1/host/profile/benchmark` | admin | Run bounded Fleet-mark benchmark (cooldown). Does not write the Market Studio result. |
| POST | `/v1/host/profile/fmsbench` | admin | Start a Forge Benchmarks Market Studio run. Profiles: `micro`, `smoke`, `standard`, `large`, `host-max-cores`, `host-max-threads`, `stress`, `full`. `full` runs standard, both host-max widths, and stress. Result is `etc/fmsbench-result.json`, separate from the hardware score. |
| GET | `/v1/mesh/benchmarks` | `read:profile` | Forge Benchmarks. The composite is an additive two-thread capacity index (PostgreSQL 22, DuckDB 28, SQLite 10, compute 12, NLP 28). `cluster_score` is the sum of complete composites, in units of this server. NLP is a shared 1 GiB embedding table. Stress stays a separate score. A peer that cannot be reached keeps its last saved row. |
| POST | `/v1/mesh/benchmarks/run` | admin | Body `{"suite":"hardware"}` or `{"suite":"market_studio","profile":"standard"}`. Starts that suite on this host and every peer. |
| POST | `/v1/host/profile/fmsbench/cleanup` | admin | Remove Market Studio containers, volumes, the runner image, and work files. Result JSON is kept. |
| GET | `/v1/host/link-probe` | `read:links` | Fixed 1 MiB body for throughput probes (`Cache-Control: no-store`). |
| GET | `/v1/mesh/links` | `read:links` | Peer RTT/throughput samples (1h/24h stats). |
| POST | `/v1/mesh/offload/advise` | `mesh:advise` | Rank local vs peers for CPU+transfer workload (`cpu_seconds`, `transfer_mb`, `service_id`). |
| GET | `/v1/services/{id}/vision` | `read:profile` | Primary/secondary vision for a service id under `etc/services/`. |
| GET | `/v1/admin/security/events` | admin | Recent guard events (`period_sec`). |
| GET | `/v1/admin/security/blocks` | admin | Active IP blocks + siege flag. |
| POST | `/v1/admin/security/blocks` | admin | Body `action=unblock`, `source=…`. |
| GET | `/v1/admin/security/agent` | admin | Matrix security agent status. |
| POST | `/v1/admin/security/agent/test` | admin | Send test alert to `#fleet-security`. |
| GET | `/v1/app-gateways` | bearer | List registered loopback app gateways (no secrets). |
| GET | `/v1/app-gateways/{id}` | bearer | Gateway metadata JSON, or upstream UI when `Accept: text/html`. |
| PUT | `/v1/app-gateways/{id}` | bearer | Register/update loopback upstream (`upstream` must be 127.0.0.1/localhost). |
| DELETE | `/v1/app-gateways/{id}` | bearer | Unregister gateway (does not stop the compose app). |
| * | `/v1/app-gateways/{id}/{path}` | bearer | Proxy to loopback app; Fleet bearer at the edge, app bearer injected upstream. Reuses HTTP/1.1 keep-alive to the upstream so each call does not open a new TCP/TLS session. Forwards `Accept`, `Accept-Language`, `Content-Type`, `If-None-Match`, `If-Modified-Since`, `X-Forge-Role`, `X-Forge-Actor`; upstream `304` and `ETag` are relayed as-is (edge CDNs may weaken the tag to `W/…`). |
| POST | `/v1/migrations` | bearer | Create a migration session (step kinds from body/recipe). |
| GET | `/v1/migrations/{id}` | bearer | Session status, bundle digests, per-step state. |
| PUT | `/v1/migrations/{id}/data-bundle` | bearer | Upload gzip tarball (or chunked session — see migration API). |
| PUT | `/v1/migrations/{id}/data-bundle/chunks/{n}` | bearer | Upload one chunk of a large data bundle (64 MiB chunks). |
| POST | `/v1/migrations/{id}/data-bundle/chunks/complete` | bearer | Finalize chunked upload and assemble bundle. |
| POST | `/v1/migrations/{id}/steps/{step_id}/run` | bearer | Run one step; `register_edge_route` completes in-process as an app gateway. |
| POST | `/v1/migrations/{id}/cancel` | bearer | Cancel pending steps and linked jobs. |
| GET | `/v1/environments` | bearer | List provisioned environments (auto-adopts existing Market Studio stacks). |
| GET | `/v1/environments/templates` | bearer | Environment templates for `POST /v1/environments`. |
| POST | `/v1/environments` | bearer | Provision environment (`seed`: `clean` or `replicate`). |
| GET | `/v1/environments/provision-log` | bearer | Async provision progress log. |
| GET | `/v1/flows` | bearer | List automation flows registered on this host. |
| POST | `/v1/flows/submit` | bearer | Submit a flow run (body: flow id + inputs). |
| POST | `/v1/fleet-apps/upgrade` | bearer | Upgrade installed app from catalog (`app_id`, optional `version`). |
| GET | `/v1/fleet-apps/{id}/about` | bearer | Installed app metadata for remote peer proxy and About UI. |
| GET | `/v1/admin/app-deployments/{sid}` | bearer | App deployment / rollout status for service id. |
| GET | `/v1/admin/forge-llm-rollout-log` | bearer | Tail Forge LLM control-plane rollout log. |
| POST | `/v1/admin/forge-llm-control-plane-rollout` | bearer | Queue Forge LLM gateway control-plane rollout. |
| POST | `/v1/admin/forge-market-studio-rollout` | bearer | Queue Forge Market Studio rollout (schema migrate gate, backup verify). |
| GET | `/v1/admin/forge-market-studio-rollout-log` | bearer | Tail Market Studio rollout log. |
| GET | `/v1/admin/forge-market-studio-rollout-contract` | bearer | Rollout contract JSON (steps, env, paths). |
| POST | `/v1/admin/forge-market-rollout-slot/release` | bearer | Emergency release of Market rollout serialization slot. |
| PUT | `/v1/admin/forge-market-source-overlay` | bearer | Gzip source overlay tarball for Market Studio dev/prod trees. |
| POST | `/v1/admin/forge-market-pattern-rollups-backfill` | bearer | Queue pattern cell rollups backfill job. |
| GET | `/v1/admin/forge-market-pattern-rollups-backfill-log` | bearer | Tail backfill log. |
| POST | `/v1/admin/sync-container-types` | bearer | Refresh `types.json` from packaged defaults. |
| GET | `/v1/host/processes` | bearer | Top host processes (`limit`, `sort=cpu|mem|pid`); Linux `/proc` sampler. |
| GET | `/v1/operator/ui-settings` | bearer | Operator UI settings + command recipes + edge checklists (`edge_recipes`). Includes `settings.edge.cache` (no API token), `gateway_edge_cache` from app registrations. |
| PUT | `/v1/operator/ui-settings` | bearer | Save operator UI settings; `edge.cache` controls origin TTLs and orchestrator sync. Write-only `cloudflare_api_token` stored in `etc/cloudflare-cache.json`. |
| POST | `/v1/admin/edge-cache/sync` | bearer | Push zone cache rules to Cloudflare when `edge.cache.orchestrate` is true on this node. |
| PUT | `/v1/app-gateways/{id}/edge-cache` | bearer or loopback app bearer | Container apps register cacheable gateway paths (`ttl_s`, `paths`). Fleet stamps `Cloudflare-CDN-Cache-Control` on proxied GET 200 responses. |
| POST | `/v1/operator/verify-public-health` | bearer | Server-side `GET {public_url}/v1/health` for Edge tab verify (body: `public_url`, `bearer_token`). |
| GET | `/v1/capacity` | bearer | Per-node CPU/RAM/GPU headroom for planning (estimates; no reservation ledger). |
| GET | `/v1/mesh/capacity` | bearer | Local capacity + cached fetch from each `remote-peers` entry (~20s TTL). |
| GET | `/v1/remote-peers` | bearer | List configured remote Fleet peers (no secrets). |
| PUT | `/v1/remote-peers/{id}` | bearer | Create/update peer (`label`, `base_url`, `bearer_token`). |
| DELETE | `/v1/remote-peers/{id}` | bearer | Remove peer from `etc/remote-peers.json`. |
| POST | `/v1/remote-peers/{id}/probe` | bearer | `GET {peer}/v1/health` smoke test. |
| GET | `/v1/remote-peers/{id}/snapshot` | bearer | Proxy to peer `GET /v1/admin/snapshot`. |
| GET | `/v1/remote-peers/{id}/processes` | bearer | Proxy to peer `GET /v1/host/processes`. |
| GET | `/v1/remote-peers/{id}/telemetry` | bearer | Proxy to peer `GET /v1/telemetry`. |
| GET | `/v1/remote-peers/{id}/jobs/{jobId}` | bearer | Proxy to peer `GET /v1/jobs/{jobId}` (read-only job details). |
| GET | `/v1/remote-peers/{id}/container-types` | bearer | Proxy to peer `GET /v1/container-types`. |
| GET | `/v1/remote-peers/{id}/container-templates` | bearer | Proxy to peer `GET /v1/container-templates`. |
| GET | `/v1/remote-peers/{id}/fleet-apps/{appId}/about` | bearer | Proxy to peer `GET /v1/fleet-apps/{appId}/about`. |
| GET | `/v1/remote-peers/{id}/capacity` | bearer | Proxy to peer `GET /v1/capacity`. |
| GET | `/v1/remote-peers/{id}/host/profile` | bearer | Proxy to peer `GET /v1/host/profile`. |
| GET | `/v1/remote-peers/{id}/mesh/links` | bearer | Proxy to peer `GET /v1/mesh/links`. |
| POST | `/v1/remote-peers/{id}/host/profile/benchmark` | bearer | Proxy to peer `POST /v1/host/profile/benchmark` (Fleet mark on that peer). |
| POST | `/v1/remote-peers/{id}/admin/upgrade` | bearer | Proxy to peer `POST /v1/admin/upgrade` using that peer's stored bearer. |
| GET | `/v1/remote-peers/{id}/admin/upgrade/status` | bearer | Proxy to peer `GET /v1/admin/upgrade/status`. |
| POST | `/v1/remote-peers/{id}/lifecycle/resume` | bearer | Proxy to peer `POST /v1/lifecycle/resume`. |
| POST | `/v1/remote-peers/{id}/host/profile/fmsbench` | bearer | Proxy to peer `POST /v1/host/profile/fmsbench` (Market Studio benchmark on that peer). |
| GET | `/v1/admin/snapshot` | bearer | Jobs, integrations, host, **`jobs_recent`** paging (`jobs_limit`, `jobs_offset`), thermal advisory, self-update meta. |
| GET | `/v1/environments/telemetry` | bearer | Per-environment Postgres **`docker stats`** rows for ready envs (same shape as **`meta.integrations.environment_telemetry`** in snapshot). |
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
| POST | `/v1/admin/git-self-update` | bearer | **Deprecated** — returns **400** `git_self_update_deprecated`. Use **`POST /v1/admin/upgrade`** after apt CDN publish. |
| GET | `/v1/lifecycle/stop-readiness` | bearer | Fleet self readiness (`stop_allowed`, `blockers[]`, `draining`). |
| POST | `/v1/lifecycle/prepare-stop` | bearer | Begin Fleet drain before upgrade. |
| POST | `/v1/lifecycle/resume` | bearer | Clear drain after failed upgrade. |
| GET | `/v1/admin/upgrade/readiness` | bearer | Aggregate readiness across dependents + Fleet. |
| GET | `/v1/admin/upgrade/status` | bearer | Active upgrade session (`queued`, `complete`, `failed`, …). |
| POST | `/v1/admin/upgrade` | bearer | Cooperative upgrade; routes by `install_channel` (apt signal or local git dev). Body: `mode`, `max_wait_sec`, `on_timeout` (`abort`|`force`), `require_apt_channel` (remote/production — **400** `migrate_to_apt_required` on git channels, answered **before** any dependent is drained), `allow_git_fallback` (with `require_apt_channel`: git-channel hosts proceed with the cooperative git upgrade and the response carries `channel_fallback` + `warning`). |
| POST | `/v1/admin/package-upgrade` | bearer | Apt only: lifecycle wait → write signal → **202** queued. |
| GET | `/v1/admin/space` | bearer | Space Guardian status: disk pressure, tier labels, last/next run, orphan/quarantine volumes. |
| POST | `/v1/admin/space/run` | bearer | Run Space Guardian tier (`tier` 0 or 1, `dry_run` default **true**). Skips when upgrade/rollout active. |
| POST | `/v1/admin/space/approve` | bearer | Approve deletion of a quarantined orphan volume (`volume_name`). |
| GET | `/v1/admin/memory` | bearer | Memory Guardian status: `MemAvailable` pressure, service classes, idle ages, dry-run stop plan (cached; not used by snapshot). |
| POST | `/v1/admin/memory/run` | bearer | Memory tier run (`tier` 0–2, `dry_run` default **true**, optional `service_id` for tier 2). Stops apply only when policy `apply_stops` is true. |
| POST | `/v1/admin/memory/ensure-running` | bearer | Wake cold target (default `host-ollama`); body `wait_sec`. Used by forge-gateway on Ollama connection failure. |
| GET | `/v1/admin/capacity/policy` | bearer | Disk + memory policy (`etc/capacity-policy.json`). |
| PUT | `/v1/admin/capacity/policy` | bearer | Merge-update capacity policy (`space`, `memory` blocks). |
| GET | `/v1/admin/cleanup-inventory` | bearer | Disk inventory: rollout pg_dump backups, migration scratch, job-workspaces, docker `system df`, protected containers, orphan volumes. |
| POST | `/v1/admin/cleanup` | bearer | Safe host cleanup (`dry_run` defaults **true**). Targets: `rollout_backups`, `migration_scratch`, `job_workspaces`, `docker_builder`, `docker_images`, `docker_images_unused`, `legacy_backup_roots`, `quarantined_volumes`, `app_gc`. Rejects `containers`, `volumes`, `docker_system_prune`. Returns pre/post operational integrity checks. |
| POST | `/v1/admin/migration-scratch-gc` | bearer | Purge stale migration bundle scratch under `migration-bundles/`. Body: `dry_run` (default false). |
| GET | `/v1/admin/install-channel` | bearer | `install_channel`, timer active, migration hints. |
| POST | `/v1/container-services` | bearer | Create managed service (`type_id`, `compose_root`, …). |
| PUT | `/v1/container-services/{id}` | bearer | Update service record. |
| DELETE | `/v1/container-services/{id}` | bearer | Delete; **409** if forge_llm still running. |
| POST | `/v1/container-services/{id}/start` | bearer | **`docker compose up`** for **forge_llm** services. |
| POST | `/v1/container-services/{id}/stop` | bearer | **`docker compose down`**. |
| POST | `/v1/managed-services/{service_id}/rollout` | bearer | Generic rollout from [rollout_registry.json](../../fleet_server/rollout_registry.json). Body: service overrides + `sync`. **409** when slot held. |
| PUT | `/v1/managed-services/{service_id}/source-overlay` | bearer | Gzip tarball overlay; layout marker from registry. Optional `?dest_root=`. |
| GET | `/v1/managed-services/{service_id}/maintenance-status` | bearer | Rollout maintenance JSON (`maintenance`, `current_step`, `eta_sec`, `progress_pct`, `job_id`, `backup_path`, `backup_verified`, …). |
| GET | `/v1/managed-services/{service_id}/rollout-log` | bearer | Tail of rollout log file for the service. |
| DELETE | `/v1/managed-services/{service_id}/rollout-slot` | bearer | Emergency release of rollout serialization slot. |
| DELETE | `/v1/managed-services/{service_id}/maintenance-status` | bearer | Clear maintenance/failure status file after operator review. |
| POST | `/v1/container-types` | bearer | Append one **`types[]` row**. |
| PUT | `/v1/container-types` | bearer | Replace full **`types.json`**. |
| PUT | `/v1/container-types/{id}` | bearer | Update one row by id. |
| DELETE | `/v1/container-types/{id}` | bearer | Delete; **409** if reserved or referenced. |
| POST | `/v1/container-templates/build` | bearer | Body **`requirement_ids`** / **`requirements`** list. |
| PUT | `/v1/container-templates` | bearer | Replace **`requirement_templates.json`**. |
| PUT | `/v1/container-templates/{id}/package` | bearer | Binary template package; query **`title`**, **`notes`**, **`replace`**. |
| POST | `/v1/services/forge-llm/start` | bearer | Legacy — start primary forge_llm. |
| POST | `/v1/services/forge-llm/stop` | bearer | Legacy — stop primary forge_llm. |
| GET | `/v1/fleet-apps/catalog` | bearer | Published FAEP catalog (`FLEET_APPS_CATALOG_URL`). |
| GET | `/v1/fleet-apps/installed` | bearer | Installed apps on this host. |
| POST | `/v1/fleet-apps/install` | bearer | Install from catalog (`app_id`, optional `version`). |
| POST | `/v1/fleet-apps/install-local` | bearer | Raw zip body; optional `X-Fleet-App-Sha256`. |
| DELETE | `/v1/fleet-apps/{id}` | bearer | Uninstall app. |
| GET | `/v1/fleet-apps/{id}/ui` | bearer | Installed app UI spec JSON. |
| GET | `/v1/fleet-apps/{id}/data/{binding}` | bearer | App data handler JSON. |
| POST | `/v1/fleet-apps/{id}/actions/{action}` | bearer | App action handler JSON. |
| GET | `/admin/apps/{id}/` | none | FAEP app host shell HTML. |
| GET | `/admin/apps/{id}/docs/{slug}` | none | In-package docs mirror HTML. |

Feature doc: [Fleet Apps API](04-fleet-apps-api.md).

### Response and query details

- **`GET /v1/health`** — CPU % from **`/proc/stat`**; memory from **`/proc/meminfo`**; **energy_ledger_kwh** cumulative on this DB (RAPL + GPU draw × time). See prior handbook text in git history for extended field lists if needed.
- **`GET /v1/telemetry`** — Periods and aliases match **[EXAMPLES.md](../build-201/05-examples-and-recipes.md)**; retention/prune via **`FLEET_TELEMETRY_RETENTION_DAYS`**, sample interval **`FLEET_TELEMETRY_INTERVAL_S`**.
- **`GET /v1/admin/snapshot`** — Integrations include **`forge_console_url`**, **`suggested_forge_llm_compose_root`**, **`container_layout`**, **`orchestration`**, Forge LLM service rows, **`cooldown_summary`** presets, **`self_update`**, and **`environment_telemetry`** (Postgres container CPU/mem per ready environment).

### Environment telemetry {#environment-telemetry}

**`GET /v1/environments/telemetry`** and **`meta.integrations.environment_telemetry`** on **`GET /v1/admin/snapshot`** return one row per **ready** environment record:

| Field | Meaning |
|-------|---------|
| `id` | Fleet environment id (e.g. `forge-market-studio--dev`) |
| `env_id` | Short env label |
| `state` | Environment state (`ready`, …) |
| `containers_total` / `containers_running` | Compose container counts |
| `postgres` | `{ container, cpu_pct, mem_pct, mem_usage_bytes, mem_limit_bytes, … }` from **`docker stats --no-stream`** |

Rows are cached ~8s server-side. Dock collectors merge these with **`GET /v1/environments`** (or Lenses **`/api/environments`**) for the **Environments** strip group.

### Rollout maintenance status {#rollout-maintenance-status}

**`GET /v1/managed-services/{service_id}/maintenance-status`** (e.g. `market-studio`, `market-studio-dev`) returns rollout progress for Forge Studio Dock and Lenses deploy UI:

| Field | Meaning |
|-------|---------|
| `maintenance` | `true` while rollout steps are running |
| `failed` | `true` after a failed step until cleared |
| `current_step` / `current_step_label` | Active pipeline step id and label |
| `steps_done` | Completed step ids |
| `eta_sec` | Rough remaining seconds from step estimates |
| `progress_pct` | 0–100 from completed steps vs pipeline step list |
| `job_id` | Active Fleet infra job when held in rollout slot (for deep links) |
| `error` / `log_tail` | Failure detail when `failed` is true |

Poll interval used by dock collector: ~5s idle, ~3s while any env reports `maintenance`.

### Forge LLM `llm_rack` (admin snapshot)

Each **`forge_llm_services[]`** entry may include **`llm_rack`** with gateway control-plane fields plus:

| Field | Meaning |
|-------|---------|
| `queue_depth` | In-flight / queued gateway requests |
| `requests_since_fleet_start` | Rollup since Fleet process start |
| `prompt_tokens_since_fleet_start` / `completion_tokens_since_fleet_start` | Token rollups since Fleet start |
| `tokens_per_sec` | Derived completion-token rate between Fleet sampler ticks |
| `active_model` / `active_mode` | Current gateway session |

Gateway **`control_plane`** is fetched with **`since_epoch`** aligned to Fleet start when available.

## Authentication

- **`FLEET_BEARER_TOKEN`** set and **`--host`** is **not** loopback-only: `/v1/...` requires `Authorization: Bearer` except where **worker** auth applies.
- **Loopback-only bind** with a token configured: bearer optional for same-machine callers unless **`FLEET_ENFORCE_BEARER=1`**.
- **No token** in env: requests accepted on any interface (development only).

## Docker workloads: live host metrics (`GET /v1/health`)

When **`FLEET_INJECT_HOST_METRICS_ENV_IN_DOCKER`** is truthy **and** **`FLEET_HOST_METRICS_BASE_URL`** is set, the runner injects **`FLEET_HOST_METRICS_URL`** and **`FLEET_HOST_METRICS_TOKEN`** (copy of bearer when set) into `docker_argv` jobs. See **[EXAMPLES.md](../build-201/05-examples-and-recipes.md)** and README — **this exposes the admin token inside containers** when enabled.

## Host Cursor CLI (`POST /v1/admin/cursor-cli`)

Admin bearer required. Runs the Cursor CLI from **`FLEET_CURSOR_AGENT_BIN`** when that absolute path is set. When it is unset, Fleet uses `/usr/local/bin/cursor-agent`, `/usr/bin/cursor-agent`, or the service user's `~/.local/bin/cursor-agent`. The request field **`credential`** is the localhost `CURSOR_API_KEY`, copied into the child environment only. It is not written to the job row, argv, or logs. `--api-key` in `args` is rejected. The response is **202** `{"ok": true, "id", "status": "queued"}`.

## Temporary host jobs (`/v1/admin/temp-jobs`)

Admin bearer required. A temp job runs on the Fleet host and returns a JSON summary. It does not accept a source archive and it refuses a result that contains filing HTML.

| Route | Purpose |
|---|---|
| `POST /v1/admin/temp-jobs` | Body `recipe` is `probe` or `python_module`. `python_module` also needs `module` under `forge_market.analysis.sec_fic.financial_facts`. Optional `args` object and `timeout_s` (1–900). Response **202** `{ok, id, status, recipe}`. |
| `GET /v1/admin/temp-jobs/{id}` | Status only: `queued`, `completed`, or `failed`. |
| `GET /v1/admin/temp-jobs/{id}/result` | JSON `result` when completed. **409** `not_ready` otherwise. |

Cursor calls this through `forge-fleet/scripts/fleet-temp-job.py` with `FORGE_FLEET_BASE_URL` and `FORGE_FLEET_BEARER_TOKEN`. Filing bytes stay on the host.

## Agentic dev rail (`/v1/admin/agentic-dev-task`)

Admin bearer required. One approved repo task runs in an **ephemeral container** built on this host from `deploy/agentic-dev/` (git, python3, node, pinned `cursor-agent`). The container clones `https://github.com/<repo>` at `origin/<base_ref>`, records `base_sha`, works on an `agent/<agent-id>/<task-id>-<slug>` branch, runs the Cursor CLI with the goal, applies the path guard and secret scan, runs `verify[]`, rebases on current `origin/<base_ref>`, pushes the branch, and opens a pull request. No host path is mounted; **git is the only code carrier**. Any guard failure returns `status: held` with `hold_reason` (`path_violation`, `secret_pattern`, `verify_failed`, `stale_conflict`, `no_changes`, …) and nothing is pushed.

| Route | Purpose |
|---|---|
| `POST /v1/admin/agentic-dev-task` | Submit `forge.agentic_dev_task.v1`: `task_id` (`req_task_<8 hex>`), `repo` (`owner/name`, must match `FLEET_AGENTIC_REPO_ALLOWLIST`, default `autowww/*`), `base_ref`, `branch` (agent lane, must contain `task_id`), `goal`, `verify[]`, `allow_paths[]`, `deny_paths[]`, `model`, `timeout_s` (60–3600), `approval{request_id,digest,event_id}`, `report{room_id,thread_root}`, `node` (`local` default, `auto`, or a remote peer id), and **either** `credential` (Cursor key) **or** `credential_ref: "courier"`. Response **202** with `id`, `status` (`queued` or `queued_waiting_credential`), `digest`, `node`. **409** `approval_digest_mismatch` when the bound digest differs from `canonical_digest(envelope)`. |
| `POST /v1/admin/agentic-dev-task/{id}/credential` | Courier attaches `{"credential": …}` once; **409** when already attached or started. |
| `GET /v1/admin/agentic-dev/pending-credentials` | Jobs in `queued_waiting_credential`: `id`, `kind`, `task_id`, `repo`, `branch`, `digest`, `approval`, `age_s`, `expired` (older than 1h). No goal text, no secrets. |
| `GET /v1/admin/agentic-dev-task/{id}` | Status, envelope, redacted `result` (`base_sha`, `head_sha`, `pr_url`, `verify[]`, `test_instructions[]`, `hold_reason`), `stderr_tail`. |
| `POST /v1/admin/code-review-task` | `forge.code_review_task.v1`: task fields plus `pr_number`, `head_sha`, `base_sha`, `confirmed_by`, `confirm_event_id`, `use_llm`, optional `merge_override{request_id,digest,event_id,approver}`. **No credential** — a `credential` field is rejected (`credential_not_allowed_for_review`); the reviewer uses only the host git token. Runs `deploy/agentic-dev/run_review.py` in the same image; result `forge.review_result.v1` (`checks[]`, `verdict pass|hold|fail`, `critical`, `merged`, `merge_sha`, `merge_error`, `required_checks_blocking`, `independent_verify`). Status `hold` → job `held`. |
| `POST /v1/admin/forge-agents-roadrunner-rollout` | `{"ref": "main", "sync": false}` — git-sync `~/forge-agents` (`FLEET_FORGE_AGENTS_ROOT`), require `<root>/.env.roadrunner`, build `deploy/roadrunner/compose.yaml`, register service type `forge_agents_roadrunner`, `compose up -d`, poll `127.0.0.1:9788/health`. **202** scheduled, **409** `rollout_in_progress`, `env_roadrunner_missing` when the env file is absent. |
| `GET /v1/admin/forge-agents-roadrunner-rollout-log` | Last rollout status and step log. |
| `GET /v1/admin/agentic-dev/capacity` | `max_running` (`FLEET_AGENTIC_DEV_MAX_RUNNING`, default 2), `running`, `free`, `agentic_dev` label. Used by peers for `node: auto`. |
| `GET /v1/admin/cursor-cli/status` | Host binary and version, runner mode (`docker`/`host`), image tag, deploy dir presence, whether the git token is configured. No credential needed. |
| `GET /v1/admin/git-identity` | `login`, `token_kind`, expiry hint for `FLEET_AGENTIC_GIT_TOKEN`. The token is never echoed. |
| `POST /v1/admin/agentic-dev/branch-gc` | `{"dry_run": true, "repos": ["owner/name"]}` — lists (and with `dry_run: false` deletes) `agent/*` branches with no open PR older than `FLEET_AGENTIC_BRANCH_TTL_DAYS` (14). |

Credentials: the git token lives only in the Fleet host environment (`FLEET_AGENTIC_GIT_TOKEN`, fine-grained PAT scoped to the allowlisted repos: Contents read/write, Pull requests read/write, Metadata read). The Cursor key is supplied per task from localhost. Neither is stored in a job row; stdout/stderr/result are redacted. Secret-looking strings in the envelope are rejected (`credential_in_request`).

Job workspace bundles (`PUT …/workspace`) reject source trees (`.git/`, a root project manifest, or more than `FLEET_BUNDLE_SOURCE_FILE_LIMIT` source files) with `source_bundle_rejected:*`; `FLEET_BUNDLE_ALLOW_SOURCE=1` opts out on a host that knowingly needs legacy behavior.

Maintainer guide: [08-agentic-dev-rail](../maintainers/08-agentic-dev-rail.md).

## Admin self-update and cooperative upgrade

### `POST /v1/admin/git-self-update`

**Deprecated** — always returns **400** `git_self_update_deprecated`. Use **`POST /v1/admin/upgrade`** after publishing to the apt CDN.

### Cooperative upgrade (`POST /v1/admin/upgrade`)

1. Detect **`install_channel`** (`git_user`, `apt_user`, `git_system`, `apt_system`).
2. **Policy gate (before any drain):** **`require_apt_channel: true`** on a git channel → **400** `migrate_to_apt_required`, unless **`allow_git_fallback: true`** is also set (then continue on the git channel and flag it in the response). Rejecting here guarantees dependents are never left in `draining` by a refused request.
3. Prepare dependents (`POST /api/lifecycle/prepare-stop` on loopback services).
4. Poll until **`stop_allowed: true`** or timeout — **409** with **`waiting_on[]`** when `on_timeout=abort`.
5. **Git channels:** `git pull` + user/system restart (response adds `channel_fallback` / `warning` when reached through `allow_git_fallback`).
6. **Apt channels:** write **`upgrade-request.json`**; root **`forge-fleet-apt-upgrade.timer`** applies within ~60s.

**`update-fleet.sh --remote-upgrade --publish-apt-cdn`** drives this end to end with no operator step: attempt 1 `require_apt_channel + allow_git_fallback` (abort on timeout); on `migrate_to_apt_required` from an older Fleet it retries without the apt requirement; on `upgrade_blocked` it retries once with `on_timeout=force` (Fleet-only restart; dependents keep running); then it polls `GET /v1/health` until `version.package_semver` equals the pushed version. `--remote-strict-apt` restores the hard refusal for hosts that must never git-pull.

Example payloads: [`lifecycle-stop-readiness-response.json`](../examples/payloads/valid/lifecycle-stop-readiness-response.json), [`upgrade-queued-response.json`](../examples/payloads/valid/upgrade-queued-response.json), [`upgrade-blocked-response.json`](../examples/payloads/valid/upgrade-blocked-response.json).

Design: [fleet-lifecycle-contract](../design/fleet-lifecycle-contract.md). Migration: [migrate-installations-to-apt](../operate/migrate-installations-to-apt.md).

## See also

- **[EXAMPLES.md](../build-201/05-examples-and-recipes.md)** — `curl` recipes.
- **[SCHEMAS.md](02-schemas-and-openapi.md)** — machine-readable schemas and **`/schemas/`** on the public site.
