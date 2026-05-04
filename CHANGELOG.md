# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
