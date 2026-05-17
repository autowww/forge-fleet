# Forge Fleet

> **One Linux host.** Bearer-aware HTTP control plane for **`docker_argv`** jobs — SQLite-backed, **`/v1/*` JSON**, **`/admin/`** dashboard — built for **Forge Lenses**, scripts, and operator runbooks.

**Forge Fleet** is a small **HTTP control plane** on **one Linux host**: it accepts **`docker_argv`** jobs over **`/v1/*` JSON**, records them in **SQLite**, tails **stdout/stderr**, optionally accepts **workspace tarballs**, resolves **container templates**, and exposes an **`/admin/`** dashboard. It is built for **Forge Lenses / Studio** automations (Docs Health and friends), scripts, and operator runbooks—not a multi-tenant scheduler.

| If you are… | Start here |
| --- | --- |
| **Local developer** trying Fleet for the first time | **[Install locally](docs/learn-101/02-install-run-local-dev.md)** → **[First job](docs/learn-101/06-first-fleet-job.md)** (about **15 min** with Docker) |
| **Host operator** putting Fleet on bare metal / systemd | **[Host bootstrap](docs/learn-101/03-host-bootstrap.md)** → **[Git install](docs/learn-101/04-git-install.md)** |
| **API / automation author** | **[HTTP API](docs/reference/01-http-api-reference.md)** + **[Examples hub](docs/examples/README.md)** |
| **Enterprise / security reviewer** | **[Security](docs/operate-301/01-security.md)** + **[Architecture](docs/operate-301/03-architecture.md)** |
| **Maintainer / releaser** | **[Maintainers](docs/maintainers/README.md)** + **`scripts/update-fleet.sh`** (below) |

**Five-minute sanity check:** with a running server, **`curl http://127.0.0.1:18765/v1/version`** (and **`/v1/health`** when bearer policy allows) should return JSON—see **[Quickstarts](docs/learn-101/05-quickstarts.md)**.

**Studio / same-host note:** Lenses typically sets **`LENSES_FLEET_URL`** / **`LENSES_FLEET_TOKEN`** to **`127.0.0.1`** or a TLS front-end so bind mounts and paths stay coherent.

## Handbook journeys

| Track | Audience | Jump in |
|-------|----------|--------|
| **Start** | “Where do I go next?” routing | **[Start hub](docs/start/README.md)** · **[Role routing table](docs/start/01-start-here.md)** |
| **Learn 101** | First install + verification | **[Learn hub](docs/learn-101/README.md)** · **[Install locally](docs/learn-101/02-install-run-local-dev.md)** · **[First job](docs/learn-101/06-first-fleet-job.md)** · **[Quickstarts](docs/learn-101/05-quickstarts.md)** |
| **Build 201** | Workspaces, templates, Caddy fronts, recipes | **[Build hub](docs/build-201/README.md)** · **[Examples & recipes](docs/build-201/05-examples-and-recipes.md)** |
| **Operate 301** | Security + runbooks + architecture + incidents | **[Operate hub](docs/operate-301/README.md)** · **[Upgrade & remote ops](docs/operate-301/05-upgrade-release-and-remote-update.md)** |
| **Reference** | Protocols & env contracts | **[Reference hub](docs/reference/README.md)** · **[HTTP API](docs/reference/01-http-api-reference.md)** · **[Schemas/OpenAPI](docs/reference/02-schemas-and-openapi.md)** |
| **Examples** | Copy-paste by language / outcome | **[Examples hub](docs/examples/README.md)** |

**Maintainer transparency:** handbook maintenance notes (**screenshots**, OpenAPI parity checks, admin KPI design prompts) ship under **[Maintainers hub](docs/maintainers/README.md)**.

**Contract invariant:** run **`python3 scripts/check-docs-contracts.py`** locally—any route in **`fleet_server/main.py`** must appear in **`docs/schemas/openapi.json`**.

## API at a glance

Fleet exposes JSON under **`/v1/`** and a browser dashboard at **`/admin/`**:

- **Version and templates** — `GET /v1/version`, `GET /v1/templates`
- **Host health and history** — `GET /v1/health`, `GET /v1/telemetry`, `GET /v1/cooldown-summary`, `POST /v1/cooldown-events`
- **Jobs and probes** — `POST /v1/jobs`, `PUT /v1/jobs/{id}/workspace`, `GET /v1/jobs/{id}`, `POST /v1/jobs/{id}/cancel`, `POST /v1/admin/test-fleet`, `POST /v1/containers/dispose`
- **Operator snapshot** — `GET /v1/admin/snapshot`
- **Container catalog and managed services** — `GET /v1/container-types`, `/v1/container-services/*`, legacy `/v1/services/forge-llm/*`
- **In-place git refresh** — `POST /v1/admin/git-self-update` ([HTTP API reference](docs/reference/01-http-api-reference.md) clarifies **`/opt`**, **`FLEET_GIT_ROOT`**, and **400** responses)

Detailed tables—including static **`/admin/…`** asset routes and host-metrics injection—live in **`[docs/reference/01-http-api-reference.md](docs/reference/01-http-api-reference.md)`**.

### Remote automation (`scripts/update-fleet.sh`)

From your **dev clone**, **`./scripts/update-fleet.sh --remote-git-self-update`** bumps/commits/pushes, then **`curl` POST** **`POST {FORGE_FLEET_BASE_URL}/v1/admin/git-self-update`** so remote hosts (**Granite**/certificator pairs, etc.) can fast-forward their install tree—see **`[docs/operate-301/05-upgrade-release-and-remote-update.md](docs/operate-301/05-upgrade-release-and-remote-update.md)`** for semantics.

Full flag matrix remains below under **Update fleet**.

## Submodules (blueprints + kitchensink)

This repo vendors read-only **`blueprints`** + **`kitchensink`** submodules (same convention as Forge / Lenses). After clone:

```bash
git submodule update --init --recursive
```

Edits belong upstream in **`autowww/blueprints`** and **`autowww/forgesdlc-kitchensink`**, never in the copied trees here.

### Install from a fresh git clone (new / remote machine)

Prereqs (**Docker CE + buildx**, Python ≥3.11, git, rsync, …): **`[docs/learn-101/03-host-bootstrap.md](docs/learn-101/03-host-bootstrap.md)`**. Then:

```bash
git clone <url> forge-fleet
cd forge-fleet
chmod +x git-install.sh   # if needed
./git-install.sh          # `--user` installs under ~/.local
```

Hands-on narrative + troubleshooting: **`[docs/learn-101/04-git-install.md](docs/learn-101/04-git-install.md)`**.

## Run locally

```bash
cd forge-fleet
export FLEET_BEARER_TOKEN='dev-token'   # optional
python3 -m fleet_server --host 127.0.0.1 --port 18765
```

Point **Studio** at `http://127.0.0.1:18765` (`LENSES_FLEET_TOKEN` mirrors **`FLEET_BEARER_TOKEN`** when bearer is enforced).

### “Update fleet” (dev → git → local production)

```bash
cd forge-fleet
./scripts/update-fleet.sh
```

**Default semantics:** submodule sync → **patch SemVer bump** → single commit (**`chore(release)`**) → **`git push origin`** → **`sudo ./install-update.sh`** (**`/opt/forge-fleet`**, port **18765**) when reachable.

**User-level installs** (**`systemctl --user`**, default port **18766**) also run **`./update-user.sh`** when **`~/.config/systemd/user/forge-fleet.service`** exists (**`./scripts/update-fleet.sh --no-user`** skips that leg). **`--no-install`** skips sudo but keeps the optional user refresh.

**Strict release (clean tree, version-only commit):** `./scripts/update-fleet.sh --strict`.

Other knobs: **`--minor`**, **`--no-push`**, **`--dry-run`**. Cursor shorthand: **`/update-fleet`** (“update fleet” rule).

Fresh host onboarding still prefers **`./git-install.sh`** after reading **`docs/learn-101/`**.

### Versioning (Studio-style semver)

- **`pyproject.toml`** → **`[project].version`** feeds **`GET /v1/version`** + `/admin/`.
- **`CHANGELOG.md`** (**`### Host operator`**) + **`docs/host-operator-steps.json`** + **`scripts/fleet-host-upgrade-hints.sh`** keep bare-metal bumps honest.
- SQLite **`fleet_schema`** stores **`package_semver`** alongside **`db_schema_version`** (**`fleet_server/versioning.py`** bumps only on breaking migrations).

### Forge LLM (forge-console) beside Fleet

Point **`FLEET_FORGE_CONSOLE_URL`** (`http://127.0.0.1:8787`, etc.) so `/admin/` exposes **Open Forge LLM console**.

### Container types + managed services (on-disk config)

Catalog + compose metadata live under **`FLEET_DATA_DIR`**:

- **`etc/containers/types.json`** defines **system/job/service** tiers + **`allow_docker_argv_jobs`** capabilities (**[container templates handbook](docs/build-201/02-container-templates.md)**).
- **`etc/services/<id>.json`** registers **`forge_llm`** stacks surfaced via **`/v1/container-services/*`**.

**`/admin/`** mirrors the swimlanes (System / Job / Service) emitted by **`GET /v1/container-types`**.

### SQLite telemetry when the HTTP server is stopped

`forge-fleet-telemetry.timer` runs **`python -m fleet_server.telemetry_sampler`** into **`fleet.sqlite`**, respecting **`FLEET_TELEMETRY_INTERVAL_S`** so systemd sampling and HTTP probes do not hammer the DB.

### Test Fleet → Lenses Attention

1. Run Fleet on Docker-capable hosts; optionally `export FLEET_LENSES_WORKSPACE_ROOT=/abs/path/to/lenses-workspace`.
2. **Studio → Settings → Fleet → Test Fleet (5 probes)** (workspace server issues **`POST /v1/admin/test-fleet`** with your saved bearer).
3. Attention bell lists **Fleet** items after jobs finalize.

Fallback probe mount: **`FLEET_LENSES_REPO_ROOT`** when packaged **`fleet_server/host_cpu_probe.py`** missing.

## Docker Compose

```bash
docker compose up --build
```

Port **18765**, named **`forge-fleet-data`** volume binds **`FLEET_DATA_DIR`**, Docker socket forwarded. Populate **`FLEET_BEARER_TOKEN`** via **`.env`** for anything beyond localhost.

Host git installs supersede Compose paths—see **`docs/learn-101/04-git-install.md`**.

TLS façade: **`[docs/build-201/03-caddy-systemd.md](docs/build-201/03-caddy-systemd.md)`** · **`scripts/install-caddy-fleet.sh`**.

### Admin shows “No jobs” but Lenses used Fleet

The **Recent jobs** table mirrors **only** **`fleet.sqlite` for this process** (`meta.sqlite_path` from **`GET /v1/admin/snapshot`** confirms the backing file):

1. **Different Fleet hosts/ports** — Studio points at `http://127.0.0.1:18765` while **`/admin/`** hits Compose on another port/instance.
2. **Ephemeral `FLEET_DATA_DIR`** — older Compose without persistent volume wiped rows on teardown.
3. **No Docs Health → Fleet offload** — Lenses stayed on inline backend or Fleet unset.

Detailed recovery steps live in **[Operate 301 troubleshooting](docs/operate-301/04-troubleshooting.md)**.

## Roadmap (deferred)

- **Forge LLM batch jobs via Fleet** — unify CLI probes + gateway traffic under job rows.
- **Template library breadth** — `GET /v1/templates` catalog growth beyond **`host_cpu_probe`** (+ **`forge_agent`** lifecycle disposing via **`POST /v1/containers/dispose`**).
- **P2 — Remote agent** — survives laptop suspend; surfaced in Lenses port-back (**`forge-lenses/docs/maintainer/docs-health-port-back.md`**).
- **P3 — Cloud adapters** — translate **`JobSpec` → Kubernetes/Nomad**.

## Limitations (MVP)

Fleet shells Docker on **the same machine supplying argv**. Override CLI path with **`FLEET_DOCKER_BIN`**. Stdout truncation keeps DB rows bounded—last JSON line must stay **`step_cli` parse-friendly for Lenses.
