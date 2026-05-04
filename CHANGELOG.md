# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.54] - 2026-05-04

### Changed

- **Certificator source-ingest** requirement templates are **no longer** copied from the `forge-fleet` package into `--data-dir`. Operators install the Dockerfile and context with **`PUT /v1/container-templates/{requirement_id}/package`** (raw **`.tar.gz` body**), then **`POST /v1/container-templates/build`**. Reference files and a packaging script live in **forge-certificators** under **`fleet-container-template/`** (see that repo’s README). Removed **`FLEET_NO_BUILTIN_CERTIFICATOR_SOURCE_INGEST_TEMPLATE`** (there is no builtin seed to disable). See [`docs/CONTAINER-TEMPLATES.md`](docs/CONTAINER-TEMPLATES.md).

### Added

- Safe tarball extraction helper **`extract_tarball_bytes_to_directory`** in [`fleet_server/workspace_bundle.py`](fleet_server/workspace_bundle.py) for template package uploads.
- Upload size and extract limits: **`FLEET_TEMPLATE_PACKAGE_UPLOAD_MAX_BYTES`**, **`FLEET_TEMPLATE_PACKAGE_MAX_UNCOMPRESSED_BYTES`**, **`FLEET_TEMPLATE_PACKAGE_MAX_FILES`**, **`FLEET_TEMPLATE_PACKAGE_MAX_PATH_DEPTH`**.

## [0.3.53] - 2026-05-04

### Fixed

- Builtin **`certificator_source_ingest_worker`** seeding: on each **`ensure_template_layout`**, refresh the on-disk Dockerfile (and vendored **`fleet_source_ingest_worker.py`**) from the packaged copy when the file still contains the deprecated **git+GitHub** `pip install` pattern or when its **SHA-256** no longer matches the bundled stock file. Upgrading **`forge-fleet`** therefore replaces stale operator data-dir files without manual SSH. See **Troubleshooting** in [`docs/CONTAINER-TEMPLATES.md`](docs/CONTAINER-TEMPLATES.md).

## [0.3.52] - 2026-05-04

### Changed

- Builtin **`certificator_source_ingest_worker`** template: Docker image no longer `pip install`s `forge-certificators` from git. The stock Dockerfile **COPY**s a vendored stdlib entrypoint and installs **PyPI** wheels (Playwright, httpx, pydantic, Jinja2). Certificator job code is expected from the **workspace tarball** (`PUT /v1/jobs/{id}/workspace`) as documented in [`docs/WORKSPACE_UPLOAD.md`](docs/WORKSPACE_UPLOAD.md).

## [0.3.49] - 2026-05-04

### Added

- Host bootstrap guide [`docs/HOST-BOOTSTRAP.md`](docs/HOST-BOOTSTRAP.md) (Docker Engine + buildx, base packages, then `git-install`).
- [`docs/host-operator-steps.json`](docs/host-operator-steps.json) and [`scripts/fleet-host-upgrade-hints.sh`](scripts/fleet-host-upgrade-hints.sh) for print-only incremental host command hints between semver versions.

### Host operator

- Prefer **Docker CE** from Docker’s apt repository with **`docker-buildx-plugin`** and **`docker-compose-plugin`** so BuildKit template builds work. Full copy-paste steps: [`docs/HOST-BOOTSTRAP.md`](docs/HOST-BOOTSTRAP.md).
- If you cannot install buildx, set **`FLEET_DOCKER_BUILDKIT=0`** in the Fleet environment file (see [`systemd/environment.example`](systemd/environment.example)).

### Automatic (no host shell steps)

- Upgrading Fleet still applies **SQLite** migrations inside the running binary when **`FLEET_DB_SCHEMA_VERSION`** increases (`fleet_server/store.py`). Refreshing the install tree remains **`git pull`**, **`git submodule update --init --recursive`**, then **`sudo ./install-update.sh`** or **`./update-user.sh`** as appropriate.

---

## Maintainer notes

- When a release needs **host-level** actions (apt packages, new env vars, one-off paths), add a **`### Host operator`** subsection under that version with copy-paste commands (or “None.”).
- Append a matching object to **[`docs/host-operator-steps.json`](docs/host-operator-steps.json)** so **`./scripts/fleet-host-upgrade-hints.sh`** can list steps between versions.
- Routine code-only releases may omit **`### Host operator`** or state that host steps are unchanged.
