# forge-fleet

Small **HTTP + bearer** orchestrator for **Docker argv** workloads (MVP: same host as Lenses so bind-mount paths match). **Forge Lenses** can set `LENSES_FLEET_URL` + `LENSES_FLEET_TOKEN` (or Studio **Settings → Fleet**) so Docs Health `session_step` runs containers via Fleet instead of in-process `docker` CLI.

## API (v1)

| Method | Path | Notes |
|--------|------|--------|
| GET | `/v1/version` | Semver + DB schema + template library: `package_semver`, `db_schema_version`, `template_lib_version`, `server_version`, optional `git_sha` (from `FLEET_GIT_SHA`). Backed by SQLite table **`fleet_schema`** (row `id=1`), updated on each `fleet.sqlite` open. |
| GET | `/v1/templates` | Container **template catalog** (`host_cpu_probe`, `forge_agent` roadmap entry, `forge_llm_console` with Fleet-managed compose paths). Bump **`FLEET_TEMPLATE_LIB_VERSION`** in `fleet_server/versioning.py` when contracts change. |
| GET | `/v1/health` | `{ "ok", "version": { … }, "host": { "cpu_usage_pct", "memory_used_pct", "loadavg_1m", "energy_ledger_kwh"?: { "rapl_kwh", "gpu_kwh", "total_kwh", "updated_epoch", "last_sample_epoch" } } }` — CPU % from Linux ``/proc/stat``; memory from ``/proc/meminfo``; **energy** is cumulative **kWh** since first Fleet sample on this DB (RAPL **package** ``energy_uj`` deltas + NVIDIA ``power.draw`` × time). Also **throttled** append to SQLite telemetry when auth passes. |
| GET | `/v1/telemetry?period=…&limit=…` | Historical samples: each row is `{ "ts", "host": { … `host_stats.snapshot()` … }, "orchestration"?: { … } }`. **`orchestration`** holds **`by_type_id`** (compose **`services_running` / `services_total`** rolled up per catalog type) and **`job_running_by_container_class`** (counts of **`running`** jobs from SQLite `meta.container_class`). Legacy rows may omit **`orchestration`** (empty object when parsed). Top-level **`energy_ledger_kwh`** in the response is the current cumulative totals. **Host `energy`:** `rapl_package_uj`, `rapl_available`, optional `rapl_instant_w`, `gpu_power_draw_w_sum`, plus **`cumulative_kwh`** on stored samples. Required **`period`** (UTC): `since_first`, `last_year`, `last_6_months`, `last_3_months`, `last_1_month`, `this_year`, `this_quarter`, `this_month`, `this_week`, `today`, `last_7_days`, `last_3_days`, `last_24_hours`, `last_8_hours`, `last_4_hours`, `last_1_hour`. Aliases: `last_365_days`→`last_year`, `last_24h`→`last_24_hours`, `last_8h`→`last_8_hours`, `last_4h`→`last_4_hours`, `last_1h`/`last_hour`→`last_1_hour`. Optional **`limit`** (default `200000`, max `500000`); `truncated` if clipped. Env: **`FLEET_TELEMETRY_INTERVAL_S`** (default `60`, min `5`), **`FLEET_TELEMETRY_RETENTION_DAYS`** (`0` = no prune). |
| GET | `/v1/cooldown-summary?period=…` | Aggregated **LLM thermal throttle** wait time (seconds) in SQLite **`fleet_cooldown_events`** (same **`period`** values as **`/v1/telemetry`**). Clients such as certificatee runs record sleeps after LLM calls — **not** “which Granite URL is active.” Configure chat/completions in **forge-certificators** (`TAXONOMY_LLM_*`); same public hostname as Fleet is possible via **`docs/CADDY-UNIFIED-GRANITE.md`**. Response: **`total_cooldown_s`**, **`event_count`**, **`window`**, **`store_bounds`**. |
| POST | `/v1/cooldown-events` | Append one recorded wait: body `{ "duration_s": <float>, "kind"?: "thermal_llm_guard", "meta"?: { … } }` → `{ "ok", "id" }`. Rows pruned with **`FLEET_TELEMETRY_RETENTION_DAYS`** (same policy as telemetry samples). |
| POST | `/v1/jobs` | Body: `{ "kind": "docker_argv", "argv": [...], "session_id": "...", "meta": { ... } }` → `{ "id": "..." }`. Jobs with **`meta.container_class` = `empty`** are rejected (internal-only). If **`meta.workspace_upload_required`** is true, the runner starts only after **`PUT /v1/jobs/{id}/workspace`** (gzip tarball). |
| PUT | `/v1/jobs/{id}/workspace` | Raw **gzip tarball** body (`Content-Type: application/gzip`). Authenticated. Extracts under the Fleet data dir and marks the workspace ready; see **`docs/WORKSPACE_UPLOAD.md`**. |
| GET | `/v1/jobs/{id}` | Status: `queued`, `running`, `completed`, `failed`, `cancelled` + `stdout` / `stderr` / `exit_code` |
| POST | `/v1/jobs/{id}/cancel` | Best-effort kill |
| GET | `/v1/admin/snapshot` | **Read-only** JSON: `meta.integrations` includes **`forge_console_url`**, **`suggested_forge_llm_compose_root`**, **`container_layout`**, **`container_types_version`**, **`forge_llm_services`**, and **`orchestration`** (same shape as telemetry: running compose totals by type + running jobs by `container_class`). Plus **`meta.version`**, **`meta.energy_ledger_kwh`**, **`meta.cooldown_summary`** (preset windows: today / this_week / this_month / this_year / since_first), `host`, **`node`**, `jobs_by_status`, **`jobs_recent`** (paged: query **`jobs_limit`** default 10 max 50, **`jobs_offset`**; response includes **`jobs_recent_total`**, **`jobs_recent_limit`**, **`jobs_recent_offset`**), `active_workers`. Throttled telemetry append stores `{ "host", "orchestration" }` (see `/v1/telemetry`). |
| POST | `/v1/containers/dispose` | Body `{ "container_id": "<docker id>" }` → `docker rm -f` (for **long-lived** agent containers). Id must match `^[0-9a-f]{12,64}$`. Studio should call this only after the workload signals completion. |
| POST | `/v1/admin/test-fleet` | Body optional `{ "count": 5 }` (capped 1–20): enqueue **host CPU probe** Docker jobs (`host_cpu_probe`). Intended for **Lenses Studio** (`POST /api/fleet/test-fleet`); not surfaced in `/admin/`. Workspace integration (**`FLEET_LENSES_WORKSPACE_ROOT`**, Attention file) is documented under **Test Fleet → Lenses Attention** below. |
| GET | `/v1/container-types` | On-disk **type catalog** from **`$FLEET_DATA_DIR/etc/containers/types.json`**: `version`, `categories[]` (MECE **system** / **job** / **service** with inherited `capabilities`), raw `types[]` (each has `category_id`; per-type booleans are optional overrides), `types_materialized[]` (same rows plus `effective_capabilities`), and `paths`. |
| GET | `/v1/container-services` | Lists **`etc/services/*.json`** with live **`forge_llm`** compose status (`docker compose ps`). |
| GET | `/v1/container-services/{id}` | One service record + status. |
| POST | `/v1/container-services` | Add a managed service: `{ "type_id": "forge_llm", "compose_root", "compose_files"?: [], "label"?: "...", "id"?: "..." }`. Omit **`id`** to auto-pick the first free id (`default`, then `lab`, then `llm2`…`llm99`). |
| PUT | `/v1/container-services/{id}` | Update `compose_root` / `compose_files` / `label` / `type_id`. |
| DELETE | `/v1/container-services/{id}` | Remove service file (`409` if compose still reports running containers). |
| POST | `/v1/container-services/{id}/start` | `docker compose up -d` using **saved** `compose_files` for that JSON. |
| POST | `/v1/container-services/{id}/stop` | `docker compose down` for that service. |
| GET | `/v1/services/forge-llm` | **Legacy** aggregate status for the primary `forge_llm` service id (`default` if present). |
| POST | `/v1/services/forge-llm/start` | **Legacy** → same as `POST /v1/container-services/<primary>/start`. |
| POST | `/v1/services/forge-llm/stop` | **Legacy** → same as `POST /v1/container-services/<primary>/stop`. |
| GET | `/admin/` | Admin UI — **kitchensink** `forge-theme.css` + `forge-fleet-admin.css` + `forge-theme.js` (Light / Dark / System), Bootstrap 5; polls snapshot for tiles/jobs. **CPU/RAM + workload charts**: history from **`telemetry_samples`** via **`GET /v1/telemetry?period=last_1_hour`**, plus a **live** point from each snapshot so traces move between sparse DB rows (~`FLEET_TELEMETRY_INTERVAL_S`). Optional **linear 0–100%** Y via `localStorage` `forgeFleetChartLinearY`; nearest-sample downsampling + polyline. **Refresh metrics**, workload summary + per-`type_id` counts under **Container types**. **Load** tile: **1m/5m/15m** mini bars + **1m** dial, raw **L 1m·5m·15m** line, ghost needle fade. **Update Fleet** appears on the version line when git self-update is configured, GitHub `master` is ahead, and the install is **not** a system tree under `/opt/forge-fleet` (system installs: **View commits** only). Zone tints: **under 25% / 25–50 / 50–75 / over 75%**. |
| GET | `/admin/static/gpu-logos/{nvidia,amd,intel}.png` | Packaged PNG logos for admin GPU tiles (served without auth; `Cache-Control: max-age=86400`). |
| GET | `/admin/ks/css/*` `GET` `/admin/ks/js/*` | Static **kitchensink** assets (only files under `kitchensink/css/` and `kitchensink/js/`) |
| GET | `/admin/theme.css` | Legacy minimal pack (optional); admin prefers `/admin/ks/css/forge-theme.css` |

Auth:

- **`FLEET_BEARER_TOKEN`** set and listen **`--host`** is **not** loopback-only (`127.0.0.1`, `::1`, `localhost`): every `/v1/...` request must send `Authorization: Bearer <token>`.
- **Loopback-only bind** (`--host 127.0.0.1` / `::1` / `localhost`) **with a token configured**: bearer is **not** required (same machine only; Lenses may still send a token). Override with **`FLEET_ENFORCE_BEARER=1`** if you need the token checked even on loopback.
- **No token** in env: requests are accepted on any bind address (avoid in production).

### Docker workloads: live host metrics (`GET /v1/health`)

When **`FLEET_INJECT_HOST_METRICS_ENV_IN_DOCKER`** is `1` / `true` / `yes` **and** **`FLEET_HOST_METRICS_BASE_URL`** is set to a base URL reachable **from inside** queued `docker run` containers (e.g. `http://172.17.0.1:18766`, or `http://host.docker.internal:18766` with `--add-host=host.docker.internal:host-gateway` in your job’s extra `docker run` flags), the Fleet runner injects, immediately after **`FLEET_JOB_ID`**:

- **`FLEET_HOST_METRICS_URL`** — same value as `FLEET_HOST_METRICS_BASE_URL` (trailing `/` stripped).
- **`FLEET_HOST_METRICS_TOKEN`** — copy of **`FLEET_BEARER_TOKEN`** when that variable is non-empty; omitted when empty (workloads can still call **`GET /v1/health`** without `Authorization` only if Fleet is bound loopback-only and auth is not enforced — uncommon from inside Docker).

Example from inside the container:

```bash
curl -sS -H "Authorization: Bearer ${FLEET_HOST_METRICS_TOKEN}" "${FLEET_HOST_METRICS_URL}/v1/health"
```

The JSON body includes **`host.cpu_usage_pct`**, **`host.memory_used_pct`**, **`host.loadavg_1m`**, and optional **`host.energy_ledger_kwh`** (see **`GET /v1/health`** row in the table above).

**Security:** this opt-in copies the **Fleet admin bearer** into the workload environment when `FLEET_BEARER_TOKEN` is set. Untrusted images or logs can leak it. Keep the flag off unless you accept that tradeoff.

### Admin self-update (git pull from UI)

When **`FLEET_GIT_ROOT`** points at a checkout with **`.git`**, **`/admin/`** offers **Update Fleet** when **GitHub `master` is ahead** of the running build (same check as the version line). **`POST /v1/admin/git-self-update`** runs `git pull --ff-only`, submodule sync, then **`update-user.sh`** / **`install-user.sh`** if present, then **`systemctl --user restart forge-fleet.service`**. Optional **`FLEET_SELF_UPDATE_POST_GIT_COMMAND`** overrides those scripts.

**Install scripts:** **`install-update.sh`** / **`install-user.sh`** (and **`update-system.sh`** / **`update-user.sh`**) rsync **`--exclude '.git/'`**, so the runtime tree has no `.git`. They now write **`FLEET_GIT_ROOT=<FLEET_SRC>`** into **`forge-fleet.env`** when the source checkout contains **`.git`**, so **`meta.self_update.configured`** becomes true after the next install refresh and restart. Ensure the service user can **`git pull`** in that directory (permissions / ownership).

- **System install** (runtime under **`/opt/forge-fleet`**, or **`FLEET_SELF_UPDATE_INSTALL_PROFILE=system`**): the admin **Update Fleet** button is hidden; **`POST /v1/admin/git-self-update`** returns **`400`** with **`system_root_install_command`** — run **`sudo ./install-update.sh`** from the clone on the host (see **`git-install.sh`** / ops docs). Git pulls still happen in **`FLEET_GIT_ROOT`** when you use that flow.

API: **`POST /v1/admin/git-self-update`** (same bearer auth as other `/v1/` routes). See **`systemd/environment.example`**.

### Remote automation (`scripts/update-fleet.sh`)

From your **dev clone**, **`./scripts/update-fleet.sh --remote-git-self-update`** runs the usual bump/commit/**push**, then **`curl`** **`POST {base}/v1/admin/git-self-update`** so a **remote** Fleet host (same machine as **forge-certificators** / Granite, if you use one URL for both) runs **`git pull --ff-only`**, submodule sync, and **`update-user.sh`** / **`systemctl --user restart forge-fleet.service`** when the remote install is **user**-profile.

- **Env:** **`FORGE_FLEET_BASE_URL`** (scheme + host + port, **no** `/v1` suffix) or **`FLEET_REMOTE_GIT_SELF_UPDATE_URL`**, plus **`FORGE_FLEET_BEARER_TOKEN`**. Overrides: **`--remote-url`**, **`--remote-bearer`**.
- **Skipped** when **`--no-push`** (nothing new on **`origin`** for the remote to pull).
- **Remote prerequisites:** runtime tree has no **`.git`** — refresh install once from a clone so **`forge-fleet.env`** gets **`FLEET_GIT_ROOT`**, or set **`FLEET_GIT_ROOT`** manually (see **`systemd/environment.example`**).
- **System install** (**`/opt/forge-fleet`**): HTTP response is **`400`** with **`system_root_install_command`** — run that **`sudo`** line on the server; unattended finish still requires SSH or manual ops.

Use **`./scripts/update-fleet.sh --dry-run --remote-git-self-update`** to print the **`curl`** plan without changing git state.

## Submodules (blueprints + kitchensink)

This repo vendors the same read-only **blueprints** and **kitchensink** submodules as other Forge sites (`forgesdlc`, `forge-lenses`, …). After clone:

```bash
git submodule update --init --recursive
```

Edits belong in the standalone `blueprints` / `forgesdlc-kitchensink` repos, not inside submodule paths here.

### Install from a fresh git clone (new / remote machine)

**OS prerequisites (Docker, Python 3.11+, git, rsync):** **[docs/HOST-BOOTSTRAP.md](docs/HOST-BOOTSTRAP.md)** — run that on a bare host before Fleet install.

If you only have a **`git clone`** on a host (no pre-existing `~/Code` checkout to rsync from), use **`./git-install.sh`**: it runs **`git submodule update --init --recursive`**, then **`sudo ./install-update.sh`** (systemd + `/opt/forge-fleet` + restart) or **`./git-install.sh --user`** for a user-level install.

```bash
git clone <url> forge-fleet
cd forge-fleet
chmod +x git-install.sh   # if needed
./git-install.sh
```

Full walkthrough, flags (`--prepare-only`, forwarding to `install-update.sh` after `--`), and troubleshooting: **[docs/GIT-INSTALL.md](docs/GIT-INSTALL.md)**. Host OS bootstrap: **[docs/HOST-BOOTSTRAP.md](docs/HOST-BOOTSTRAP.md)**.

## Run locally

```bash
cd forge-fleet
export FLEET_BEARER_TOKEN='dev-token'   # optional
python3 -m fleet_server --host 127.0.0.1 --port 18765
```

Point Lenses at `http://127.0.0.1:18765` and set the same token in Studio Fleet settings or `LENSES_FLEET_TOKEN`.

### “Update fleet” (dev → git → local production)

One script propagates **this checkout** to **`origin`** and refreshes the **systemd** install (`/opt/forge-fleet`, port **18765**):

```bash
cd forge-fleet
./scripts/update-fleet.sh
```

**Default (what “update fleet” should do):** submodules; **patch** SemVer bump in `pyproject.toml`; **`git add -A`** and a single commit; **`git push`** to **`origin`** (creates upstream on first push); **`sudo ./install-update.sh`** (rsync → `/opt`, unit, **restart** `forge-fleet.service`). Requires remote **`origin`**.

**User-level Fleet** (`~/.local/share/forge-fleet`, systemd **`--user`**, default port **18766**): if **`~/.config/systemd/user/forge-fleet.service`** exists, the same script then runs **`./update-user.sh`** (no sudo): rsync from this checkout into the user install tree and **restarts** `forge-fleet.service` for that user. Use **`./scripts/update-fleet.sh --no-user`** to skip that step. With **`--no-install`**, the user step still runs when the unit file is present (so you can refresh a user install without touching `/opt`).

**Strict release** (clean tree, version-only commit): `./scripts/update-fleet.sh --strict`

You can always run **`./update-user.sh`** alone after a `git pull` (same as `install-user.sh` for an existing user layout).

Other flags: **`--minor`**, **`--no-push`**, **`--no-install`**, **`--no-user`**, **`--dry-run`**. In Cursor: slash command **`/update-fleet`** or say **“update fleet”** (rule **forge-fleet-update-fleet**). New host from clone: **`./git-install.sh`** — **[docs/GIT-INSTALL.md](docs/GIT-INSTALL.md)**.

### Versioning (Studio-style semver)

- **Shipped version** lives in **`pyproject.toml`** → `[project].version` (same idea as Lenses Studio reading `package.json` / Vite). Bump it for every release you want operators to see in `/admin/` and `GET /v1/version`.
- **Operator-facing release notes** and **host-level upgrade commands**: **`CHANGELOG.md`** (`### Host operator`); machine-readable companion **`docs/host-operator-steps.json`**; print hints with **`./scripts/fleet-host-upgrade-hints.sh`** (see **`docs/HOST-BOOTSTRAP.md`**).
- **SQLite** table **`fleet_schema`** stores `package_semver` + **`db_schema_version`**. Bump **`FLEET_DB_SCHEMA_VERSION`** in `fleet_server/versioning.py` only when `fleet_server/store.py` adds a breaking migration (then implement the step in `_run_fleet_schema_migrations`).
- Optional **`FLEET_GIT_SHA`** (or `SOURCE_GIT_COMMIT`) for short SHA in API/admin.

### Forge LLM (forge-console) beside Fleet

Set **`FLEET_FORGE_CONSOLE_URL`** (e.g. `http://127.0.0.1:8787`) so `/admin/` shows an **Open Forge LLM console** link.

### Container types + managed services (on-disk config)

Fleet persists **container class metadata** and **forge-llm compose instances** under the same **`--data-dir`** as `fleet.sqlite` — the directory **`install-user.sh`** sets as `FLEET_USER_DATA` or **`install-update.sh`** sets as `FLEET_DATA`:

- **`etc/containers/types.json`** — **versioned** catalog: top-level **`categories[]`** define MECE orchestration contracts (**system** = internal, **job** = run-to-completion including probes, **service** = long-lived compose under `etc/services/`). Each **`types[]`** row has **`category_id`** and inherits **`capabilities`** (`admin_spawnable`, `api_manage_services`, `allow_docker_argv_jobs`) from its category unless a field is set on the type. Older v1 files without `categories` / `category_id` are merged **on read** into this shape (no automatic disk rewrite). `empty` stays internal-only (not queued via `/v1/jobs`).
- **`etc/services/<id>.json`** — each **forge_llm** stack: `compose_root`, `compose_files` overlays, `label`. **Start/stop** always read this file (no ad-hoc compose list on start).

If **`FLEET_FORGE_LLM_ROOT`** is set and `etc/services/` is empty, Fleet writes **`default.json` once** (same behavior as before for env-first installs). Prefer **`POST /v1/container-services`** for explicit registration.

**`/admin/`** shows container types as **three swimlanes** (System / Job / Service) from the catalog API; configured paths; each **forge_llm** service with **Start/Stop**; and a small form to **POST** new services.

Deeper integration (Fleet-issued batch jobs wrapping forge-llm CLI) remains optional future work.

### SQLite telemetry when the HTTP server is stopped

**`install-user.sh`** / **`install-update.sh`** install **`forge-fleet-telemetry.timer`**, which runs **`python -m fleet_server.telemetry_sampler`** (or **`fleet-telemetry-sample`**) into the same **`fleet.sqlite`** as **`fleet-server`**, honoring **`FLEET_TELEMETRY_INTERVAL_S`**. Throttling uses the latest row in **`telemetry_samples`**, so the timer and **`/v1/health`** / **`/v1/admin/snapshot`** do not double-write inside the interval.

### Test Fleet → Lenses Attention

1. Run Fleet on a host with Docker; optional: `export FLEET_LENSES_WORKSPACE_ROOT=/abs/path/to/your/lenses-workspace` (must match the workspace Lenses Studio is serving).
2. In **Lenses Studio** → **Settings** → **Fleet**, click **Test Fleet (5 probes)** (the workspace server calls `POST /v1/admin/test-fleet` with your saved Fleet bearer — not from the browser).
3. When jobs finish, refresh Lenses (or wait for scan cache); the bell shows a **Fleet** item linking to Fleet settings.

Optional: `FLEET_LENSES_REPO_ROOT` — if the bundled `fleet_server/host_cpu_probe.py` is missing, point at a checkout of `forge-lenses` so Fleet mounts `lenses/sandbox/host_cpu_probe.py` instead.

## Docker Compose

```bash
docker compose up --build
```

Default compose maps port **18765**, mounts **`forge-fleet-data`** on `FLEET_DATA_DIR` so **Recent jobs** in `/admin/` survive container restarts, and passes Docker socket for `docker run`. Set `FLEET_BEARER_TOKEN` in `.env` for non-dev use. In `/admin/`, **Recent jobs** is a short human summary (status, workload label, time, outcome); **Details** opens a modal with full job id, session, Docker argv, meta JSON, and stdout/stderr (via `GET /v1/jobs/{id}`).

For a **host install from git** (not Compose), prefer **`./git-install.sh`** after clone — see **[docs/GIT-INSTALL.md](docs/GIT-INSTALL.md)** and **[docs/HOST-BOOTSTRAP.md](docs/HOST-BOOTSTRAP.md)**.

**Caddy on systemd:** **[docs/CADDY-SYSTEMD.md](docs/CADDY-SYSTEMD.md)** · **`scripts/install-caddy-fleet.sh`** (interactive; user or system layout, ports, bearer).

### Admin shows “No jobs” but Lenses used Fleet

The **Recent jobs** table only lists rows in **this process’s** `fleet.sqlite` (see `meta.sqlite_path` from `GET /v1/admin/snapshot` if you need the path). Common causes:

1. **Different Fleet instance** — e.g. Lenses points at `http://127.0.0.1:18765` served by a **host** `python3 -m fleet_server` while you open admin against **Docker** (or another port). Each process has its own DB.
2. **Ephemeral DB** — older compose without a volume: every `docker compose down` wiped job rows. Current `compose.yaml` uses a named volume for `FLEET_DATA_DIR`.
3. **No Docs Health Fleet path** — Lenses never called Fleet (inline backend, or Fleet URL unset, or step was `apply` which stays on the host).

## Roadmap (deferred)

- **Forge LLM batch jobs via Fleet:** submit `docker_argv` (or dedicated kind) that runs forge-llm CLI / calls **forge-gateway** with the same env pattern as `forge-llm/apps/forge-console`; surface status in Fleet admin and Lenses (compose lifecycle is covered by **`etc/services/*.json`** + `/v1/container-services/*`).
- **Template library:** `GET /v1/templates` is the catalog; **`host_cpu_probe`** matches Lenses `lenses/sandbox/host_cpu_probe.py` (see `probe_contract` in payload). **`forge_agent`:** generic image with `GITPATH`, git clone + user script, completion signal to Fleet, **no auto-dispose** — Lenses calls **`POST /v1/containers/dispose`** when the operator tears the session down.
- **P2 — Remote agent:** worker registers from another host; jobs survive laptop sleep; Lenses shows completed jobs for port-back (see `forge-lenses/docs/maintainer/docs-health-port-back.md`).
- **P3 — Cloud adapters:** same `JobSpec` translated to Kubernetes Job, Nomad batch, or Temporal — avoid reinventing durable execution at scale.

## Limitations (MVP)

- Fleet runs `docker` on **the same machine** that built the argv (paths are host paths). The runner resolves the Docker CLI with a widened `PATH` (includes `/snap/bin`); override with **`FLEET_DOCKER_BIN`** in `forge-fleet.env` if needed.
- Stdout is capped in DB for safety; last JSON line must remain parseable for Lenses `step_cli` contract.
