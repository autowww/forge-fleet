# Build 201 — Integration recipes index

Pick a row, gather the **prereqs**, open the **guide**, and validate the **expected output** before deep-diving **[Examples & recipes](05-examples-and-recipes.md)**.

| Use case | Who | Prerequisites | Guide | Expected output |
| --- | --- | --- | --- | --- |
| **Health / version probes** | SRE, integrator | Fleet listening | **[Quickstarts](../learn-101/05-quickstarts.md)** · **[curl examples](../examples/curl.md)** | **`GET /v1/version`** and **`/v1/health`** return **200** JSON |
| **Hello-world `docker_argv` job** | Developer | Docker on Fleet host | **[First job](../learn-101/06-first-fleet-job.md)** · **[jobs examples](../examples/jobs.md)** | **HTTP 201** create; job **`completed`** |
| **Stateful job + workspace tarball** | Integrator | Workspace manifest policy understood | **[Workspace upload](01-workspace-upload.md)** · **[workspace examples](../examples/workspace-upload.md)** | **`meta.workspace_state`** becomes **`ready`**; runner starts |
| **Template-backed images** | Platform | Docker + buildx policy | **[Container templates](02-container-templates.md)** · **[examples](../examples/container-templates.md)** | Resolve/build succeeds; job uses rewritten image |
| **TLS / Caddy front** | Operator | DNS + certs | **[Caddy + systemd](03-caddy-systemd.md)** · **[Caddy healthcheck example](../examples/caddy-healthcheck.md)** | **`https://host/v1/health`** OK |
| **Granite / unified hostname** | Operator | Multiple backends | **[Caddy unified Granite](04-caddy-unified-granite.md)** | Single hostname routes to Fleet + peers |
| **Managed `forge_llm` service** | Integrator | Compose stack available | **[HTTP API](../reference/01-http-api-reference.md)** · **[managed services example](../examples/managed-services.md)** | Service **start/stop** via API |
| **Operator visibility** | Operator | Bearer for snapshot | **[Admin + Studio](../learn-101/07-admin-dashboard-and-studio.md)** | **`GET /v1/admin/snapshot`** reflects live jobs |
| **Remote git self-update** | Maintainer | Host shell + git layout | **[Upgrade & remote ops](../operate-301/05-upgrade-release-and-remote-update.md)** · **[self-update example](../examples/self-update-automation.md)** | **`POST /v1/admin/git-self-update`** **`ok: true`** or documented **400** hand-off |

When wiring **Forge Lenses / Studio**, start with **[Admin dashboard & Studio](../learn-101/07-admin-dashboard-and-studio.md)** so tokens + URLs land in **`LENSES_FLEET_*`**.

**Language starters:** **[Examples hub](../examples/README.md)** (Python / TypeScript / CI smoke).
