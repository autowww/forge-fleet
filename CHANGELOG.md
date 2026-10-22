# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.145] - 2026-10-22

### Changed

- Handbook refresh for fleet.forgesdlc.com: operate nav covers **`docs/operate/`** and **`docs/adr/`**, admin dashboard tour, API reference gaps closed, OpenAPI parity restored (**129** routes).

## [0.3.139] - 2026-10-15

### Added

- **Capacity** admin tab: Space Guardian + Memory Guardian UI, policy editor, mesh/security panels on **`/admin/`**.

### Host operator

- Apt **`forge-fleet`** / **`forge-fleet-user`** debs ship memory guardian daemon wiring when policy **`apply_stops`** is enabled.

## [0.3.127] - 2026-09-28

### Added

- **Space Guardian** self-healing disk tiers: **`GET/POST /v1/admin/space*`**, orphan volume quarantine, app GC inventory — [`docs/maintainers/06-space-guardian.md`](docs/maintainers/06-space-guardian.md).

## [0.3.118] - 2026-09-14

### Changed

- Fleet **apt CDN only** for production debs (**packages.forgesdlc.com**); **`update-fleet.sh --publish-apt-cdn`** integrated into release workflow.

### Host operator

- Production hosts should migrate git installs to apt — [`docs/learn-101/10-migrate-to-apt.md`](docs/learn-101/10-migrate-to-apt.md).

## [0.3.107] - 2026-09-02

### Added

- **Pattern cell rollups backfill** admin API: **`POST /v1/admin/forge-market-pattern-rollups-backfill`**.

## [0.3.99] - 2026-08-22

### Added

- **N-environment** Forge Market Studio rollout on Granite; environment telemetry on admin snapshot and **`GET /v1/environments/telemetry`**.

## [0.3.96] - 2026-08-18

### Added

- **Fleet environments API** (`GET/POST /v1/environments`, templates, provision log) — ADR [`docs/adr/adr-fleet-environments.md`](docs/adr/adr-fleet-environments.md).

## [0.3.135] - 2026-10-08

### Fixed

- Cooperative **upgrade** resumes every dependent after upgrade ends or aborts; stale queued jobs no longer veto upgrades indefinitely.

## [0.3.133] - 2026-10-06

### Added

- **Remote Fleet upgrade** completes via **`POST /v1/admin/upgrade`** on git-channel hosts (no operator SSH); **`allow_git_fallback`** + apt CDN publish from **`update-fleet.sh`**.

## [0.3.82] - 2026-07-28

### Added

- **Migrations API** (`POST /v1/migrations`, chunked data-bundle upload) for Granite Market cutover — [`docs/build-201/09-migration-api.md`](docs/build-201/09-migration-api.md).

## [0.3.81] - 2026-07-27

### Added

- Chunked migration data-bundle upload (**64 MiB** chunks).

## [0.3.80] - 2026-07-26

### Added

- **GW-2** **`/v1/migrations`** API scaffold for managed compose cutover recipes.

## [0.3.68] - 2026-06-02

### Added

- Handbook **Start** hub role-path rail, doc-hydration example job template, standout learn guide.

## [0.3.61] - 2026-05-17

### Changed

- Documentation: expanded handbook IA (Start → Learn → Build → Operate → Reference → Examples), job-create examples aligned with **`kind: docker_argv`** and **HTTP 201**, broadened link + public-copy CI checks, OpenAPI **`operationId`** + path parameters + **`POST /v1/jobs`** request schema reference, schema-validated example payload, operate-301 backup/observability/enterprise checklist pages.

## [0.3.54] - 2026-05-04

### Changed

- **Certificator source-ingest** requirement templates are **no longer** copied from the `forge-fleet` package into `--data-dir`. Operators install the Dockerfile and context with **`PUT /v1/container-templates/{requirement_id}/package`** (raw **`.tar.gz` body**), then **`POST /v1/container-templates/build`**. Reference files and a packaging script live in **forge-certificators** under **`fleet-container-template/`** (see that repo’s README). Removed **`FLEET_NO_BUILTIN_CERTIFICATOR_SOURCE_INGEST_TEMPLATE`** (there is no builtin seed to disable). See [`docs/build-201/02-container-templates.md`](docs/build-201/02-container-templates.md).

### Added

- Safe tarball extraction helper **`extract_tarball_bytes_to_directory`** in [`fleet_server/workspace_bundle.py`](fleet_server/workspace_bundle.py) for template package uploads.
- Upload size and extract limits: **`FLEET_TEMPLATE_PACKAGE_UPLOAD_MAX_BYTES`**, **`FLEET_TEMPLATE_PACKAGE_MAX_UNCOMPRESSED_BYTES`**, **`FLEET_TEMPLATE_PACKAGE_MAX_FILES`**, **`FLEET_TEMPLATE_PACKAGE_MAX_PATH_DEPTH`**.

## [0.3.53] - 2026-05-04

### Fixed

- Builtin **`certificator_source_ingest_worker`** seeding: on each **`ensure_template_layout`**, refresh the on-disk Dockerfile (and vendored **`fleet_source_ingest_worker.py`**) from the packaged copy when the file still contains the deprecated **git+GitHub** `pip install` pattern or when its **SHA-256** no longer matches the bundled stock file. Upgrading **`forge-fleet`** therefore replaces stale operator data-dir files without manual SSH. See **Troubleshooting** in [`docs/build-201/02-container-templates.md`](docs/build-201/02-container-templates.md).

## [0.3.52] - 2026-05-04

### Changed

- Builtin **`certificator_source_ingest_worker`** template: Docker image no longer `pip install`s `forge-certificators` from git. The stock Dockerfile **COPY**s a vendored stdlib entrypoint and installs **PyPI** wheels (Playwright, httpx, pydantic, Jinja2). Certificator job code is expected from the **workspace tarball** (`PUT /v1/jobs/{id}/workspace`) as documented in [`docs/build-201/01-workspace-upload.md`](docs/build-201/01-workspace-upload.md).

## [0.3.49] - 2026-05-04

### Added

- Host bootstrap guide [`docs/learn-101/03-host-bootstrap.md`](docs/learn-101/03-host-bootstrap.md) (Docker Engine + buildx, base packages, then `git-install`).
- [`docs/host-operator-steps.json`](docs/host-operator-steps.json) and [`scripts/fleet-host-upgrade-hints.sh`](scripts/fleet-host-upgrade-hints.sh) for print-only incremental host command hints between semver versions.

### Host operator

- Prefer **Docker CE** from Docker’s apt repository with **`docker-buildx-plugin`** and **`docker-compose-plugin`** so BuildKit template builds work. Full copy-paste steps: [`docs/learn-101/03-host-bootstrap.md`](docs/learn-101/03-host-bootstrap.md).
- If you cannot install buildx, set **`FLEET_DOCKER_BUILDKIT=0`** in the Fleet environment file (see [`systemd/environment.example`](systemd/environment.example)).

### Automatic (no host shell steps)

- Upgrading Fleet still applies **SQLite** migrations inside the running binary when **`FLEET_DB_SCHEMA_VERSION`** increases (`fleet_server/store.py`). Refreshing the install tree remains **`git pull`**, **`git submodule update --init --recursive`**, then **`sudo ./install-update.sh`** or **`./update-user.sh`** as appropriate.

---

## Maintainer notes

- When a release needs **host-level** actions (apt packages, new env vars, one-off paths), add a **`### Host operator`** subsection under that version with copy-paste commands (or “None.”).
- Append a matching object to **[`docs/host-operator-steps.json`](docs/host-operator-steps.json)** so **`./scripts/fleet-host-upgrade-hints.sh`** can list steps between versions.
- Routine code-only releases may omit **`### Host operator`** or state that host steps are unchanged.
