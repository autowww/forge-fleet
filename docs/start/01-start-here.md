# Start here — Forge Fleet docs

Pick the track that matches your role. Each link jumps to the right handbook page inside the **Start** structure.

## Fleet in one view

Text-only sketch (a Kitchen Sink **network** / **linear** diagram will mirror this in **[What is Fleet?](../learn-101/01-what-is-fleet.md)** — track status in **[`docs/maintainers/VISUAL-COVERAGE.md`](../maintainers/VISUAL-COVERAGE.md)**):

1. **Client** (**curl**, Studio, scripts) calls **`POST /v1/jobs`** with **`kind: docker_argv`**.
2. **Fleet** stores the row in **SQLite**, optionally waits for **workspace upload**, then spawns the runner.
3. **Docker / Podman** executes **`argv`**; stdout/stderr stream back into the job row for **`GET /v1/jobs/{id}`**.

| I want to… | Go to |
|------------|-------|
| Run Fleet **locally** on my machine (dev loop) | **[Install locally](../learn-101/02-install-run-local-dev.md)** · **[Quickstarts](../learn-101/05-quickstarts.md)** · **[Your first job](../learn-101/06-first-fleet-job.md)** · **[Repository README](../../README.md)** |
| Install Fleet on a **fresh host** (systemd, Docker) | **[Host bootstrap](../learn-101/03-host-bootstrap.md)** · **[Git install](../learn-101/04-git-install.md)** · **[Caddy + systemd](../build-201/03-caddy-systemd.md)** |
| Call the **HTTP API** from scripts or **`curl`** | **[HTTP API reference](../reference/01-http-api-reference.md)** · **[Examples hub](../examples/README.md)** · **[Schemas](../reference/02-schemas-and-openapi.md)** |
| Integrate **Lenses / Studio** (workspace, Test Fleet) | **[README](../../README.md)** (Fleet env summary) · **[Forge LCDL vs Fleet](../reference/04-forge-lcdl-relationship.md)** · **[Workspace upload](../build-201/01-workspace-upload.md)** · **[Admin + Studio](../learn-101/07-admin-dashboard-and-studio.md)** |
| Use **requirement templates** and container images | **[Container templates](../build-201/02-container-templates.md)** |
| Put Fleet **behind TLS / Caddy** (incl. unified Granite) | **[Caddy + systemd](../build-201/03-caddy-systemd.md)** · **[Caddy unified Granite](../build-201/04-caddy-unified-granite.md)** |
| **Release or self-update** Fleet on a box I maintain | **[Repository README](../../README.md)** (**Remote automation**) · **[Upgrade & remote ops](../operate-301/05-upgrade-release-and-remote-update.md)** |

**Verification triad** (any track): after the server is up, **`GET /v1/version`** and **`GET /v1/health`** should return JSON—see **[Examples & recipes](../build-201/05-examples-and-recipes.md)** or **[Quickstarts](../learn-101/05-quickstarts.md)**.

**Concept map:** **[What is Fleet?](../learn-101/01-what-is-fleet.md)** (+ **[Start hub overview](README.md)**).

**Next track:** when installs feel solid, continue to **[Learn 101 hub](../learn-101/README.md)** → **[Build 201](../build-201/README.md)** → **[Operate 301](../operate-301/README.md)** → **[Reference](../reference/README.md)**.
