# Fleet examples hub

Production-style snippets grouped **by outcome** (jobs, workspaces, templates, telemetry, CI). Prefer **`FLEET_BASE_URL`** / **`BASE`** and **`FLEET_TOKEN`** placeholders—never paste real bearer tokens into tickets.

**When stuck:** cross-check shapes in **[Schemas & OpenAPI](../reference/02-schemas-and-openapi.md)** and long-form narrative **[Examples & recipes](../build-201/05-examples-and-recipes.md)**.

**Canonical job-create JSON:** **[`payloads/valid/job-create-request.json`](payloads/valid/job-create-request.json)**.

| Topic | Page |
|-------|------|
| Auth + **`curl`** ergonomics | **[curl.md](curl.md)** |
| Minimal **Python** (**stdlib** only) | **[python.md](python.md)** |
| **TypeScript / `fetch`** (Node 20+) | **[typescript-fetch.md](typescript-fetch.md)** |
| Jobs lifecycle | **[jobs.md](jobs.md)** · **[Learn 101 — First job](../learn-101/06-first-fleet-job.md)** |
| Workspace tarball flow | **[workspace-upload.md](workspace-upload.md)** |
| Container templates API | **[container-templates.md](container-templates.md)** |
| Managed **`forge_llm`** services | **[managed-services.md](managed-services.md)** |
| Telemetry + host health | **[telemetry.md](telemetry.md)** |
| TLS / Caddy health probe | **[caddy-healthcheck.md](caddy-healthcheck.md)** |
| **`git-self-update`** flows | **[self-update-automation.md](self-update-automation.md)** |
| CI smoke recipe | **[ci-smoke.md](ci-smoke.md)** |
| Lenses / Studio wiring | **[lenses-studio.md](lenses-studio.md)** |
| HTTP error cookbook | **[error-handling.md](error-handling.md)** |

Canonical long-form **`curl`** appendix: **[Examples & recipes](../build-201/05-examples-and-recipes.md)**.

**Validation:** maintainer notes in **`[EXAMPLES-VALIDATION.md](../maintainers/EXAMPLES-VALIDATION.md)`** — CI covers **`check-docs-contracts.py`**, **`check-docs-examples.py`**, **`check-schema-examples.py`** ( **`payloads/valid/`** must validate; **`payloads/invalid/*.invalid.*.json`** must fail), and **`check-openapi-quality.py`**.
