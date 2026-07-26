---
title: Start
nav_order: 1
page_contract_profile: landing
landing_blocks:
  role_path_rail:
    paths:
      - persona: Local dev
        title: Install locally
        body: venv, Compose, first verification
        href: ../learn-101/02-install-run-local-dev.md
      - persona: Host ops
        title: Host bootstrap
        body: systemd, Docker on fresh machine
        href: ../learn-101/03-host-bootstrap.md
      - persona: API
        title: HTTP API
        body: curl, schemas, examples
        href: ../reference/01-http-api-reference.md
      - persona: Studio
        title: Lenses integration
        body: workspace upload and admin tour
        href: ../learn-101/07-admin-dashboard-and-studio.md
      - persona: TLS
        title: Caddy + systemd
        body: TLS and unified Granite layout
        href: ../build-201/03-caddy-systemd.md
---

# Start

> **Pick your path first** — then dive into Learn, Build, or Operate. For the mental model, start with **[What is Fleet?](../learn-101/01-what-is-fleet.md)**.

Use this section to **pick your path**. For the product mental model first, open **[Learn 101 — What is Fleet?](../learn-101/01-what-is-fleet.md)**.

## Choose your track

<!-- ks-landing:role_path_rail -->

| I want to… | Go here |
|------------|--------|
| **Route by role** (local, API, TLS, Studio, templates) | [Start here routing table](01-start-here.md) |
| **Learn** installs, verification, **`/admin/`**, Lenses wiring | [Learn 101 hub](../learn-101/README.md) |
| **Build** jobs, workspaces, templates, TLS / Caddy, examples | [Build 201 hub](../build-201/README.md) |
| **Operate** production ops, architecture, troubleshooting | [Operate 301 hub](../operate-301/README.md) |
| **Look up** endpoints, schemas, env vars | [Reference hub](../reference/README.md) |
| **Maintain** handbook build, screenshots, prompts | [Maintainers hub](../maintainers/README.md) (_may advance faster than Fleet releases_) |

Quick verification once the server is up: **`GET /v1/version`** and **`GET /v1/health`** (see **[Quickstarts](../learn-101/05-quickstarts.md)**).
