# Learn 101 — What is Fleet?

**Outcome:** explain Fleet to another engineer without opening **`fleet_server/main.py`**.

Forge Fleet is a **small HTTP service** (optional **bearer** auth) that **accepts JSON job specs**, stores lifecycle + logs in **SQLite**, and **runs `docker_argv` workloads on the same host**. Operators use **`/admin/`** for recent jobs and host telemetry.

**Audience:** engineers onboarding · **~15 min** · **Verify:** restate **`docker_argv`**, **`/v1/jobs`**, and **`/admin/`**.

## Mental model and fit

```text
 Client (curl / Studio ) --> Fleet HTTP (/v1/*) --> SQLite job rows --> Docker CLI --> Container stdout/stderr --> Fleet tails --> GET /v1/jobs/{id}
```

```blueprint-diagram-ascii
key: linear
alt: Fleet HTTP path from client to SQLite ledger and Docker runner
caption: Clients call /v1; Fleet persists jobs; Docker runs argv; clients poll job status.
Client -> Fleet API -> SQLite -> Docker runner -> logs -> Poll GET job
```

**Use Fleet when** you need a **central job ledger** (`GET /v1/jobs/{id}` + log tails), **Forge Lenses Studio offload** (Docs Health **`session_step`** via Fleet instead of in-process **`docker`**), or **operator dashboards** (`/admin/` telemetry and optional **`git-self-update`**).

**Avoid Fleet today for** **remote Docker / K8s-only** workloads (bind mounts assume **same-host** paths), **multi-tenant SaaS isolation** without hardened VMs/networks ([**Operate 301 — Security**](../operate-301/01-security.md)), or **governed LLM orchestration** — use **`forge-lcdl`** for LLM tasks; Fleet runs containers, not LLM pipelines.

## Concepts, troubleshoot, and next steps

Reference vocabulary, quick fixes, and where to go next—kept as scannable lists so the opener stays narrative-led.

### Core concepts

- **Fleet server** — **`fleet_server`** exposing **`/v1/*`** and **`/admin/`**
- **Job** — `POST /v1/jobs` **docker_argv** (`argv`, `session_id`, **`meta`**)
- **`docker_argv`** — argv vector for **`docker run`** semantics
- **Workspace upload** — optional **`PUT /v1/jobs/{id}/workspace`** gzip tarball
- **Template** — **`GET /v1/templates`** catalog / requirement builds
- **Container type** — **`system` / `job` / `service`** via **`etc/containers/types.json`**
- **Managed service** — long-lived stacks (`forge_llm`) under **`etc/services/`**
- **Admin snapshot** — **`GET /v1/admin/snapshot`** JSON for dashboards
- **Telemetry** — **`telemetry_samples`** + **`GET /v1/telemetry`**
- **Bearer token** — shared secret when auth policy requires it

**Typical ports:** dev/Compose **18765**; user install (**`install-user.sh`**) **18766**; Playwright docs **19876** (disposable **`FLEET_DATA_DIR`**). Aim Studio, **`curl`**, and **`/admin/`** at the **same instance**—each process owns its **`fleet.sqlite`**.

**Related products:** **Forge Lenses / Studio** (Settings → Fleet); **Blueprints / ForgeSDLC** (handbook ecosystem, not runtime); **`forge-lcdl`** (governed LLM library, not embedded in Fleet).

### Troubleshooting snapshot

- Jobs empty in **`/admin/`** but Studio “works” — confirm URLs map to the **same** Fleet ([**Admin tour**](07-admin-dashboard-and-studio.md) FAQ).
- **`401`/`403`** everywhere — bearer vs bind-address mismatch ([**Security**](../operate-301/01-security.md)).

### Verify

Explain aloud:

1. Where **`fleet.sqlite`** lives (**`FLEET_DATA_DIR`**).
2. Difference between **`docker_argv`** jobs vs managed **`forge_llm`** services.
3. Why bind-mount paths care about **same-host** Studio.

### Next steps

- **[Install & run locally](02-install-run-local-dev.md)** — install on your machine.
- **[Host bootstrap](03-host-bootstrap.md)** — fresh OS prep.
- **[Quickstarts](05-quickstarts.md)** — guided **`curl`** proofs.

Deep protocol tables remain in **[HTTP API](../reference/01-http-api-reference.md)**—finish **Learn 101** before living there permanently. Deeper paths: **Operate 301 — Security**, **Reference — LCDL ↔ Fleet**, **Build 201** workspace upload and container templates.
