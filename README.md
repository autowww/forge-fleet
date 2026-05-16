# Forge Fleet

Small **HTTP + bearer** orchestrator for **Docker argv** workloads (MVP: same host as Lenses so bind-mount paths match). **Forge Lenses** can set `LENSES_FLEET_URL` + `LENSES_FLEET_TOKEN` (or Studio **Settings → Fleet**) so Docs Health `session_step` runs containers via Fleet instead of in-process `docker` CLI.

## Start here

- **[Overview](docs/OVERVIEW.md)** — what Fleet is for, mental model, typical ports, documentation map, and agent-oriented notes.
- **[HTTP API (v1)](docs/API-REFERENCE.md)** — full `/v1/*` and `/admin/` route table, bearer rules, host-metrics env injection, and **`POST /v1/admin/git-self-update`**.
- **[Install from git](docs/GIT-INSTALL.md)** and **[host bootstrap](docs/HOST-BOOTSTRAP.md)** — new machine setup (`./git-install.sh`, OS packages).
- **[Forge LCDL](docs/FORGE-LCDL.md)** — how the **Fleet** orchestrator relates to (and does not replace) the separate **`forge-lcdl`** governed-LLM library.

## API at a glance

Fleet exposes JSON under **`/v1/`** and a browser dashboard at **`/admin/`**:

- **Version and templates** — `GET /v1/version`, `GET /v1/templates`
- **Host health and history** — `GET /v1/health`, `GET /v1/telemetry`, `GET /v1/cooldown-summary`, `POST /v1/cooldown-events`
- **Jobs and probes** — `POST /v1/jobs`, `PUT /v1/jobs/{id}/workspace`, `GET /v1/jobs/{id}`, `POST /v1/jobs/{id}/cancel`, `POST /v1/admin/test-fleet`, `POST /v1/containers/dispose`
- **Operator snapshot** — `GET /v1/admin/snapshot`
- **Container catalog and managed services** — `GET /v1/container-types`, `/v1/container-services/*`, legacy `/v1/services/forge-llm/*`
- **In-place git refresh** — `POST /v1/admin/git-self-update` (see API reference for system-tree **`/opt`** behavior)

The complete table (including static **`/admin/...`** assets), authentication matrix, and Docker host-metrics opt-in are in **[docs/API-REFERENCE.md](docs/API-REFERENCE.md)**.

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
- Optional **`FLEET_GIT_SHA`** (or `SOURCE_GIT_COMMIT`) for short SHA in API/admin; **`scripts/set-fleet-git-root-in-env.sh`** sets it from the install source checkout. If unset, Fleet probes **`FLEET_GIT_ROOT`** when it is a git checkout; if **`FLEET_GIT_ROOT`** is unset, it probes the running tree when that tree still has **`.git`** (typical dev).

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
