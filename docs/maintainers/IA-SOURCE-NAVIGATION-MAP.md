# Fleet handbook — IA path map (v1)

_Map for maintainers_: how former flat `docs/*.md` pages map onto the handbook **Learn 101 · Build 201 · Operate 301 · Reference** layout. Canonical URLs on the published site flatten these paths under the handbook generator.

## Root (GitHub + handbook)

| File | Role |
|------|------|
| `README.md` | Handbook **home** (`index.html`) — product framing + anchors into sections |
| `CHANGELOG.md` | Top-level changelog page (Convention: Keep a Changelog) |
| `docs/schemas/` | OpenAPI + JSON Schema — mirrored to Hosting `/schemas/` by **forge-fleet-website** build |

## `docs/start/`

| New path | Former path |
|-----------|--------------|
| [README.md](../start/README.md) | *(new hub)* |
| [01-start-here.md](../start/01-start-here.md) | `docs/START-HERE.md` |

## `docs/learn-101/`

| New path | Former / source |
|-----------|----------------|
| [README.md](../learn-101/README.md) | *(new hub)* |
| [01-what-is-fleet.md](../learn-101/01-what-is-fleet.md) | derived from removed `OVERVIEW.md` (concept + ports) |
| [02-install-run-local-dev.md](../learn-101/02-install-run-local-dev.md) | *(new — dev loop before bootstrap)* |
| [03-host-bootstrap.md](../learn-101/03-host-bootstrap.md) | `HOST-BOOTSTRAP.md` |
| [04-git-install.md](../learn-101/04-git-install.md) | `GIT-INSTALL.md` |
| [05-quickstarts.md](../learn-101/05-quickstarts.md) | `QUICKSTARTS.md` |
| [06-first-fleet-job.md](../learn-101/06-first-fleet-job.md) | *(new — job lifecycle walk-through)* |
| [07-admin-dashboard-and-studio.md](../learn-101/07-admin-dashboard-and-studio.md) | derived from `OVERVIEW.md` (`/admin/`, screenshots, IDE phrases) |

## `docs/examples/`

| New path | Former / source |
|-----------|----------------|
| [README.md](../examples/README.md) | *(new hub — prompt pack **08**)* |
| Supporting **`*.md`** pages | Topic stubs linking back to Learn / Build / Reference |

## `docs/build-201/`

| New path | Former path |
|-----------|--------------|
| [README.md](../build-201/README.md) | *(new hub)* |
| [01-workspace-upload.md](../build-201/01-workspace-upload.md) | `WORKSPACE_UPLOAD.md` |
| [02-container-templates.md](../build-201/02-container-templates.md) | `CONTAINER-TEMPLATES.md` |
| [03-caddy-systemd.md](../build-201/03-caddy-systemd.md) | `CADDY-SYSTEMD.md` |
| [04-caddy-unified-granite.md](../build-201/04-caddy-unified-granite.md) | `CADDY-UNIFIED-GRANITE.md` |
| [05-examples-and-recipes.md](../build-201/05-examples-and-recipes.md) | `EXAMPLES.md` |
| [06-integration-recipes-index.md](../build-201/06-integration-recipes-index.md) | *(new curated index)* |

## `docs/operate-301/`

| New path | Former path |
|-----------|--------------|
| [README.md](../operate-301/README.md) | *(new hub)* |
| `01-security.md` | `SECURITY.md` |
| `02-operations-runbook.md` | `OPERATIONS-RUNBOOK.md` |
| `03-architecture.md` | `ARCHITECTURE.md` |
| `04-troubleshooting.md` | `TROUBLESHOOTING.md` |
| `05-upgrade-release-and-remote-update.md` | *(new synthesis — release/self-update operations)* |

## `docs/reference/`

| New path | Former path |
|-----------|--------------|
| [README.md](../reference/README.md) | *(new hub)* |
| `01-http-api-reference.md` | `API-REFERENCE.md` |
| `02-schemas-and-openapi.md` | `SCHEMAS.md` |
| `03-configuration-and-env.md` | `CONFIGURATION.md` |
| `04-forge-lcdl-relationship.md` | `FORGE-LCDL.md` |
| `05-workspace-localization-scope.md` | `WORKSPACE-LOCALIZATION-SCOPE.md` |

## `docs/maintainers/`

| New path | Former path |
|-----------|--------------|
| [README.md](../maintainers/README.md) | *(new hub)* |
| `01-admin-status-overview-design.md` | `ADMIN-STATUS-OVERVIEW-DESIGN.md` |
| `02-docker-integration-test-prompt.md` | `PROMPT-run-docker-integration-test.md` |
| `03-handbook-contracts-and-ci.md` | *(new — `check-docs-contracts.py`, handbook builds)* |
| `VISUAL-COVERAGE.md` | *(prompt **09** — page ↔ visual map)* |
| `EXAMPLES-VALIDATION.md` | *(prompt **08** — manual validation cadence)* |
| `DOCS-RELEASE-CHECKLIST.md` | *(prompt **12** — pre-publish gates)* |

`docs/assets/README.md` stays in place (PNG sources for handbook).
