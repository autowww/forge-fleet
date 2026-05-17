# Build 201 — Practitioner guides

**Purpose:** ship **realistic integrations**—workspace uploads, template builds, **`curl`**, **Caddy / TLS**, and Granite-style routing—without re-reading the full route table each time.

| | |
| --- | --- |
| **Audience** | Integrators and host operators past first install |
| **Effort** | **~2–6 hours** per topic (TLS/DNS can dominate wall time) |
| **Prerequisites** | Finished **[Learn 101](../learn-101/README.md)** or equivalent; Docker + Fleet running |
| **Success** | You can run a **workspace upload** or **template-backed** path and verify it from **`GET /v1/jobs/{id}`** or **`/admin/`** |

## At a glance

- **You will:** move from “Fleet runs” to “Fleet runs **my** tarball / template / TLS front”.
- **Cadence:** tackle one topic per session; Caddy + DNS often dominate wall time.
- **Companion:** keep **[HTTP API](../reference/01-http-api-reference.md)** open for exact routes.

| Topic | Page |
|------|------|
| Tarball workspaces | **[Workspace upload](01-workspace-upload.md)** |
| Requirement templates + BuildKit builds | **[Container templates](02-container-templates.md)** |
| Caddy on systemd hosts | **[Caddy + systemd](03-caddy-systemd.md)** |
| Single hostname routing (Fleet + Granite) | **[Caddy unified Granite](04-caddy-unified-granite.md)** |
| Topic-based snippets (Python / TS / CI) | **[Examples library](../examples/README.md)** |
| Copy‑paste **`curl`** / **`jq`** | **[Examples & recipes](05-examples-and-recipes.md)** |
| Curated integrations index | **[Integration recipes hub](06-integration-recipes-index.md)** |

**Before:** **[Learn 101](../learn-101/README.md)** · **After:** **[Operate 301](../operate-301/README.md)** · **Lookup:** **[HTTP API](../reference/01-http-api-reference.md)** · **[Schemas](../reference/02-schemas-and-openapi.md)**
