# forge-fleet

Small **HTTP + bearer** orchestrator for **Docker argv** workloads (MVP: same host as Lenses so bind-mount paths match). **Forge Lenses** can set `LENSES_FLEET_URL` + `LENSES_FLEET_TOKEN` (or Studio **Settings → Fleet**) so Docs Health `session_step` runs containers via Fleet instead of in-process `docker` CLI.

## API (v1)

| Method | Path | Notes |
|--------|------|--------|
| GET | `/v1/version` | Semver + DB schema + template library: `package_semver`, `db_schema_version`, `template_lib_version`, `server_version`, optional `git_sha` (from `FLEET_GIT_SHA`). Backed by SQLite table **`fleet_schema`** (row `id=1`), updated on each `fleet.sqlite` open. |
| GET | `/v1/templates` | Container **template catalog** (`host_cpu_probe`, `forge_agent` roadmap entry, `forge_llm_console` with Fleet-managed compose paths). Bump **`FLEET_TEMPLATE_LIB_VERSION`** in `fleet_server/versioning.py` when contracts change. |
| GET | `/v1/health` | `{ "ok", "version": { … }, "host": { "cpu_usage_pct", "memory_used_pct", "loadavg_1m", "energy_ledger_kwh"?: { "rapl_kwh", "gpu_kwh", "total_kwh", "updated_epoch", "last_sample_epoch" } } }` — CPU % from Linux ``/proc/stat``; memory from ``/proc/meminfo``; **energy** is cumulative **kWh** since first Fleet sample on this DB (RAPL **package** ``energy_uj`` deltas + NVIDIA ``power.draw`` × time). Also **throttled** append to SQLite telemetry when auth passes. |
| GET | `/v1/telemetry?period=…&limit=…` | Historical **host** indicator samples: `samples` is `[{ "ts", "host": { … snapshot() …, `energy.cumulative_kwh` on rows written after ledger exists } }, …]`. Top-level **`energy_ledger_kwh`** is the current cumulative totals. **Host `energy`:** `rapl_package_uj`, `rapl_available`, `gpu_power_draw_w_sum` (NVIDIA sum), plus **`cumulative_kwh`** on stored samples. Required **`period`** (UTC): `since_first`, `last_year`, `last_6_months`, `last_3_months`, `last_1_month`, `this_year`, `this_quarter`, `this_month`, `this_week`, `today`, `last_7_days`, `last_3_days`, `last_24_hours`, `last_8_hours`, `last_4_hours`, `last_1_hour`. Aliases: `last_365_days`→`last_year`, `last_24h`→`last_24_hours`, `last_8h`→`last_8_hours`, `last_4h`→`last_4_hours`, `last_1h`/`last_hour`→`last_1_hour`. Optional **`limit`** (default `200000`, max `500000`); `truncated` if clipped. Env: **`FLEET_TELEMETRY_INTERVAL_S`** (default `60`, min `5`), **`FLEET_TELEMETRY_RETENTION_DAYS`** (`0` = no prune). |
| POST | `/v1/jobs` | Body: `{ "kind": "docker_argv", "argv": [...], "session_id": "...", "meta": { ... } }` → `{ "id": "..." }`. Jobs with **`meta.container_class` = `empty`** are rejected (internal-only). |
| GET | `/v1/jobs/{id}` | Status: `queued`, `running`, `completed`, `failed`, `cancelled` + `stdout` / `stderr` / `exit_code` |
| POST | `/v1/jobs/{id}/cancel` | Best-effort kill |
| GET | `/v1/admin/snapshot` | **Read-only** JSON: `meta.integrations` includes **`forge_console_url`**, **`container_layout`** (paths to `etc/containers/types.json` and `etc/services/`), **`container_types_version`**, and **`forge_llm_services`** (per-service compose ps summary). Plus **`meta.version`**, **`meta.energy_ledger_kwh`** (same shape as health), `host` (includes **`energy`** observation), **`node`**, `jobs_by_status`, `jobs_recent`, `active_workers`. Throttled telemetry append from `host` (see `/v1/telemetry`). |
| POST | `/v1/containers/dispose` | Body `{ "container_id": "<docker id>" }` → `docker rm -f` (for **long-lived** agent containers). Id must match `^[0-9a-f]{12,64}$`. Studio should call this only after the workload signals completion. |
| POST | `/v1/admin/test-fleet` | Body optional `{ "count": 5 }` (capped 1–20): enqueue **host CPU probe** Docker jobs (`host_cpu_probe`). Intended for **Lenses Studio** (`POST /api/fleet/test-fleet`); not surfaced in `/admin/`. Workspace integration (**`FLEET_LENSES_WORKSPACE_ROOT`**, Attention file) is documented under **Test Fleet → Lenses Attention** below. |
| GET | `/v1/container-types` | On-disk **type catalog** from **`$FLEET_DATA_DIR/etc/containers/types.json`** (`admin_spawnable`, `api_manage_services`, notes). |
| GET | `/v1/container-services` | Lists **`etc/services/*.json`** with live **`forge_llm`** compose status (`docker compose ps`). |
| GET | `/v1/container-services/{id}` | One service record + status. |
| POST | `/v1/container-services` | Add a managed service: `{ "id", "type_id": "forge_llm", "compose_root", "compose_files"?: [], "label"?: "..." }`. |
| PUT | `/v1/container-services/{id}` | Update `compose_root` / `compose_files` / `label` / `type_id`. |
| DELETE | `/v1/container-services/{id}` | Remove service file (`409` if compose still reports running containers). |
| POST | `/v1/container-services/{id}/start` | `docker compose up -d` using **saved** `compose_files` for that JSON. |
| POST | `/v1/container-services/{id}/stop` | `docker compose down` for that service. |
| GET | `/v1/services/forge-llm` | **Legacy** aggregate status for the primary `forge_llm` service id (`default` if present). |
| POST | `/v1/services/forge-llm/start` | **Legacy** → same as `POST /v1/container-services/<primary>/start`. |
| POST | `/v1/services/forge-llm/stop` | **Legacy** → same as `POST /v1/container-services/<primary>/stop`. |
| GET | `/admin/` | Admin UI — **kitchensink** `forge-theme.css` + `forge-theme.js` (Light / Dark / System), Bootstrap 5; polls snapshot (no full page reload). **Overview** is one horizontal **row**: **CPU** tile (progress bar, mean per-logical-core busy %, **MHz** avg + **cpufreq** governor / **EPP** when sysfs exposes them), **memory** (four quarter “banks”), **load** (three mini gauges for **1m / 5m / 15m** vs registered max + **peak 1m %** in **localStorage** `forgeFleetLoadScaleMax`, `forgeFleetLoadPeakPct`), **disk**, **GPU**. Zone tints: **under 25% / 25–50 / 50–75 / over 75%** (green → amber → light red → dark red). **GPU:** vendor **PNG** logos from ``GET /admin/static/gpu-logos/{nvidia,amd,intel}.png``; if **no** vendor has live device rows, a single gray **stub** tile shows all three logos; otherwise only tiles for vendors with telemetry. |
| GET | `/admin/static/gpu-logos/{nvidia,amd,intel}.png` | Packaged PNG logos for admin GPU tiles (served without auth; `Cache-Control: max-age=86400`). |
| GET | `/admin/ks/css/*` `GET` `/admin/ks/js/*` | Static **kitchensink** assets (only files under `kitchensink/css/` and `kitchensink/js/`) |
| GET | `/admin/theme.css` | Legacy minimal pack (optional); admin prefers `/admin/ks/css/forge-theme.css` |

Auth:

- **`FLEET_BEARER_TOKEN`** set and listen **`--host`** is **not** loopback-only (`127.0.0.1`, `::1`, `localhost`): every `/v1/...` request must send `Authorization: Bearer <token>`.
- **Loopback-only bind** (`--host 127.0.0.1` / `::1` / `localhost`) **with a token configured**: bearer is **not** required (same machine only; Lenses may still send a token). Override with **`FLEET_ENFORCE_BEARER=1`** if you need the token checked even on loopback.
- **No token** in env: requests are accepted on any bind address (avoid in production).

## Submodules (blueprints + kitchensink)

This repo vendors the same read-only **blueprints** and **kitchensink** submodules as other Forge sites (`forgesdlc`, `forge-lenses`, …). After clone:

```bash
git submodule update --init --recursive
```

Edits belong in the standalone `blueprints` / `forgesdlc-kitchensink` repos, not inside submodule paths here.

### Install from a fresh git clone (new / remote machine)

If you only have a **`git clone`** on a host (no pre-existing `~/Code` checkout to rsync from), use **`./git-install.sh`**: it runs **`git submodule update --init --recursive`**, then **`sudo ./install-update.sh`** (systemd + `/opt/forge-fleet` + restart) or **`./git-install.sh --user`** for a user-level install.

```bash
git clone <url> forge-fleet
cd forge-fleet
chmod +x git-install.sh   # if needed
./git-install.sh
```

Full walkthrough, flags (`--prepare-only`, forwarding to `install-update.sh` after `--`), and troubleshooting: **[docs/GIT-INSTALL.md](docs/GIT-INSTALL.md)**.

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

**Strict release** (clean tree, version-only commit): `./scripts/update-fleet.sh --strict`

Other flags: **`--minor`**, **`--no-push`**, **`--no-install`**, **`--dry-run`**. In Cursor: slash command **`/update-fleet`** or say **“update fleet”** (rule **forge-fleet-update-fleet**). New host from clone: **`./git-install.sh`** — **[docs/GIT-INSTALL.md](docs/GIT-INSTALL.md)**.

### Versioning (Studio-style semver)

- **Shipped version** lives in **`pyproject.toml`** → `[project].version` (same idea as Lenses Studio reading `package.json` / Vite). Bump it for every release you want operators to see in `/admin/` and `GET /v1/version`.
- **SQLite** table **`fleet_schema`** stores `package_semver` + **`db_schema_version`**. Bump **`FLEET_DB_SCHEMA_VERSION`** in `fleet_server/versioning.py` only when `fleet_server/store.py` adds a breaking migration (then implement the step in `_run_fleet_schema_migrations`).
- Optional **`FLEET_GIT_SHA`** (or `SOURCE_GIT_COMMIT`) for short SHA in API/admin.

### Forge LLM (forge-console) beside Fleet

Set **`FLEET_FORGE_CONSOLE_URL`** (e.g. `http://127.0.0.1:8787`) so `/admin/` shows an **Open Forge LLM console** link.

### Container types + managed services (on-disk config)

Fleet persists **container class metadata** and **forge-llm compose instances** under the same **`--data-dir`** as `fleet.sqlite` — the directory **`install-user.sh`** sets as `FLEET_USER_DATA` or **`install-update.sh`** sets as `FLEET_DATA`:

- **`etc/containers/types.json`** — which `container_class` values exist and whether Fleet **admin** or **API** may create/manage them (`empty` is never admin-spawnable and cannot be queued via `/v1/jobs`).
- **`etc/services/<id>.json`** — each **forge_llm** stack: `compose_root`, `compose_files` overlays, `label`. **Start/stop** always read this file (no ad-hoc compose list on start).

If **`FLEET_FORGE_LLM_ROOT`** is set and `etc/services/` is empty, Fleet writes **`default.json` once** (same behavior as before for env-first installs). Prefer **`POST /v1/container-services`** for explicit registration.

**`/admin/`** lists types (read-only), shows configured paths, lists each **forge_llm** service with **Start/Stop**, and includes a small form to **POST** new services.

Deeper integration (Fleet-issued batch jobs wrapping forge-llm CLI) remains optional future work.

### Test Fleet → Lenses Attention

1. Run Fleet on a host with Docker; optional: `export FLEET_LENSES_WORKSPACE_ROOT=/abs/path/to/your/lenses-workspace` (must match the workspace Lenses Studio is serving).
2. In **Lenses Studio** → **Settings** → **Fleet**, click **Test Fleet (5 probes)** (the workspace server calls `POST /v1/admin/test-fleet` with your saved Fleet bearer — not from the browser).
3. When jobs finish, refresh Lenses (or wait for scan cache); the bell shows a **Fleet** item linking to Fleet settings.

Optional: `FLEET_LENSES_REPO_ROOT` — if the bundled `fleet_server/host_cpu_probe.py` is missing, point at a checkout of `forge-lenses` so Fleet mounts `lenses/sandbox/host_cpu_probe.py` instead.

## Docker Compose

```bash
docker compose up --build
```

Default compose maps port **18765**, mounts **`forge-fleet-data`** on `FLEET_DATA_DIR` so **Recent jobs** in `/admin/` survive container restarts, and passes Docker socket for `docker run`. Set `FLEET_BEARER_TOKEN` in `.env` for non-dev use.

For a **host install from git** (not Compose), prefer **`./git-install.sh`** after clone — see **[docs/GIT-INSTALL.md](docs/GIT-INSTALL.md)**.

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

- Fleet runs `docker` on **the same machine** that built the argv (paths are host paths).
- Stdout is capped in DB for safety; last JSON line must remain parseable for Lenses `step_cli` contract.
