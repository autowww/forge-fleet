# Fleet handbook — UX page inventory

Flat list of **product** Markdown sources compiled into the public handbook (excluding vendored `blueprints/`). Slug pattern follows `forge-autodoc` (`slug_from_md_path`): root `README.md` → `index.html`, `CHANGELOG.md` → `changelog.html`, `docs/<section>/...` → `docs-....html`.

## Core journeys

| Markdown path | Section | Primary audience |
|---------------|---------|------------------|
| `README.md` | Home | All |
| `docs/start/README.md` | Start | Routing |
| `docs/start/01-start-here.md` | Start | Role table |
| `docs/learn-101/README.md` | Learn 101 | New users |
| `docs/learn-101/01-what-is-fleet.md` | Learn 101 | Concept |
| `docs/learn-101/02-install-run-local-dev.md` | Learn 101 | Developer |
| `docs/learn-101/03-host-bootstrap.md` | Learn 101 | Operator |
| `docs/learn-101/04-git-install.md` | Learn 101 | Operator |
| `docs/learn-101/05-quickstarts.md` | Learn 101 | All |
| `docs/learn-101/06-first-fleet-job.md` | Learn 101 | Developer |
| `docs/learn-101/07-admin-dashboard-and-studio.md` | Learn 101 | Power user |
| `docs/build-201/README.md` | Build 201 | Practitioner |
| `docs/build-201/01-workspace-upload.md` | Build 201 | Practitioner |
| `docs/build-201/02-container-templates.md` | Build 201 | Practitioner |
| `docs/build-201/03-caddy-systemd.md` | Build 201 | Practitioner |
| `docs/build-201/04-caddy-unified-granite.md` | Build 201 | Practitioner |
| `docs/build-201/05-examples-and-recipes.md` | Build 201 | Practitioner |
| `docs/build-201/06-integration-recipes-index.md` | Build 201 | Practitioner |
| `docs/operate-301/README.md` | Operate 301 | Production |
| `docs/operate-301/01-security.md` | Operate 301 | Security |
| `docs/operate-301/02-operations-runbook.md` | Operate 301 | Ops |
| `docs/operate-301/03-architecture.md` | Operate 301 | Architecture |
| `docs/operate-301/04-troubleshooting.md` | Operate 301 | Ops |
| `docs/operate-301/05-upgrade-release-and-remote-update.md` | Operate 301 | Release |
| `docs/operate-301/06-backup-restore-and-disaster-recovery.md` | Operate 301 | DR |
| `docs/operate-301/07-observability-and-slos.md` | Operate 301 | SRE |
| `docs/operate-301/08-enterprise-deployment-checklist.md` | Operate 301 | Enterprise |

## Reference and examples

| Markdown path | Notes |
|---------------|--------|
| `docs/reference/README.md` | Hub |
| `docs/reference/01-http-api-reference.md` | API tables |
| `docs/reference/02-schemas-and-openapi.md` | Schemas |
| `docs/reference/03-configuration-and-env.md` | Env |
| `docs/reference/04-forge-lcdl-relationship.md` | LCDL |
| `docs/reference/05-workspace-localization-scope.md` | i18n |
| `docs/examples/README.md` | Hub |
| `docs/examples/*.md` | Task-oriented samples |

## Internal / transparency

| Markdown path | Nav placement |
|---------------|-----------------|
| `docs/maintainers/*` | **More → Maintainers** |
| `docs/design/*` | **More → Design hub** |
| `CHANGELOG.md` | **More → Changelog** |
| `docs/assets/README.md` | Linked from maintainer / asset docs |

## IA manifest

Authoritative top-level structure: [`site-nav.yaml`](../site-nav.yaml) under **forge-fleet** `docs/`. The website generator passes it via `HandbookBuildConfig.site_nav_yaml`.
