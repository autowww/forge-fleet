---
content_id: forge.docs.fleet.what-is-fleet
canonical_owner: forge-fleet
primary_persona: operator
reader_stage: discover
maturity: demonstrated
evidence_level: canonical_doc
refresh_policy: on_claim_change
last_reviewed: '2026-07-03'
---

# Learn 101 — What is Fleet?

**Outcome:** explain Fleet to another engineer without opening **`fleet_server/main.py`**.

**Audience:** any engineer evaluating or onboarding to Fleet. **Time:** ~15 minutes. **Prerequisites:** none. **Verify:** you can restate what **`docker_argv`**, **`/v1/jobs`**, and **`/admin/`** are for.

## Plain-language definition

Forge Fleet is a **small HTTP service** (optional **bearer** authentication) that **accepts JSON job specs**, persists lifecycle + logs in **SQLite**, and **runs `docker_argv` workloads on the same Linux/macOS host**. Operators inspect recent jobs and host telemetry via **`/admin/`**.

## When to use Fleet

| Scenario | Why Fleet fits |
|----------|----------------|
| **Forge Lenses Studio offload** | Docs Health **`session_step`** runs containers **via Fleet** instead of in-process **`docker`** |
| **Central job ledger + logs** | SQLite-backed **`GET /v1/jobs/{id}`** + stdout/stderr tails |
| **Operator dashboards** | **`/admin/`** surfaces CPU/RAM/service swimlanes plus optional **`git-self-update`** hooks |

## When **not** to use Fleet (today)

| Scenario | Prefer instead |
|----------|----------------|
| **Remote Docker hosts / Kubernetes-only fleets** | MVP binds mounts assume **same host** paths |
| **Multi-tenant SaaS isolation** | Fleet trusts operators—combine with hardened VMs/network segments (**[Security](../operate-301/01-security.md)**) |
| **Deterministic governed LLM orchestration** | **`forge-lcdl`** handles LLM tasks—Fleet runs containers (**[Forge LCDL ↔ Fleet](../reference/04-forge-lcdl-relationship.md)**) |

## Mental model

```blueprint-diagram
key: linear
alt: Fleet HTTP path from client to SQLite ledger and Docker runner
title: Fleet HTTP job lifecycle
summary: How clients submit docker_argv jobs, Fleet persists state, Docker runs workloads, and callers poll for completion.
node: Client
detail: Submits a docker_argv job spec over HTTP to Fleet.
more: POST /v1/jobs carries argv, session_id, and optional meta; bearer auth applies when the server policy requires it.
node: Fleet API
detail: Validates the request and opens a bounded execution path.
more: The fleet_server process exposes /v1/* endpoints and hands accepted jobs to the local runner on the same host.
node: SQLite
detail: Records job lifecycle, status, and operator-visible history.
more: Each Fleet instance owns one fleet.sqlite under FLEET_DATA_DIR; Studio and curl must target the same instance to see the same ledger.
node: Docker runner
detail: Runs the argv vector with docker run semantics on the host.
more: Bind mounts assume same-host paths as the caller; docker_argv is the literal argv handed to Docker.
node: logs
detail: Captures stdout and stderr tails for reviewable audit.
more: GET /v1/jobs/{id} returns lifecycle plus log tails so operators and Studio can inspect outcomes without shell access.
node: Poll GET job
detail: Caller polls until the job reaches a terminal state.
more: Clients use GET /v1/jobs/{id} to track queued, running, succeeded, or failed status rather than blocking on the container.
caption: Clients call /v1; Fleet persists jobs; Docker runs argv; clients poll job status.
fallback_ascii: |
  Client -> Fleet API -> SQLite -> Docker runner -> logs -> Poll GET job
```

| Concept | Meaning |
|---------|--------|
| **Fleet server** | **`fleet_server`** process exposing **`/v1/*`** & **`/admin/`** |
| **Job** | `POST /v1/jobs` **docker_argv** request (`argv`, `session_id`, **`meta`**) |
| **`docker_argv`** | Literal argv vector handed to **`docker run`** semantics |
| **Workspace upload** | Optional **`PUT /v1/jobs/{id}/workspace`** gzip tarball (**[Build 201](../build-201/01-workspace-upload.md)**) |
| **Template** | **`GET /v1/templates`** catalog entries / requirement builds (**[Templates](../build-201/02-container-templates.md)**) |
| **Container type** | MECE **`system` / `job` / `service`** classification via **`etc/containers/types.json`** |
| **Managed service** | Long-lived compose stacks (`forge_llm`) registered under **`etc/services/`** |
| **Admin snapshot** | **`GET /v1/admin/snapshot`** JSON bundle for dashboards |
| **Telemetry** | SQLite **`telemetry_samples`** + **`GET /v1/telemetry`** windows |
| **Bearer token** | Shared secret (`Authorization` header) whenever auth policy demands it |

## Typical ports

| Context | Port | Notes |
|---------|------|------|
| Dev / Compose “standard” | **18765** | `python3 -m fleet_server --port 18765` |
| User install (**`install-user.sh`**) | **18766** | **`systemd --user`** default |
| Playwright docs screenshots | **19876** | Disposable **`FLEET_DATA_DIR`** (**`e2e/`**) |

Always aim Studio + **`curl`** + **`/admin/`** at the **same Fleet instance**—each process owns its **`fleet.sqlite`**.

## Relationship map

| Thing | Relationship |
|-------|----------------|
| **Forge Lenses / Studio** | Primary integration surface (**Settings → Fleet**) |
| **Blueprints / ForgeSDLC** | Methodology + handbook ecosystem—not runtime deps |
| **`forge-lcdl`** | Adjacent governed-LLM library—**not** embedded in Fleet |

## Troubleshooting snapshot

| Symptom | First move |
|---------|------------|
| Jobs empty in **`/admin/`** but Studio “works” | Confirm URLs map to **same** Fleet (**[Admin tour](07-admin-dashboard-and-studio.md)** FAQ) |
| **`401`/`403`** everywhere | Bearer vs bind-address mismatch (**[Security](../operate-301/01-security.md)**) |

## Verify

Explain aloud:

1. Where **`fleet.sqlite`** lives (**`FLEET_DATA_DIR`**).
2. Difference between **`docker_argv`** jobs vs managed **`forge_llm`** services.
3. Why bind-mount paths care about **same-host** Studio.

## Next steps

| Step | Doc |
|------|-----|
| Install locally | **[Install & run locally](02-install-run-local-dev.md)** |
| Fresh OS prep | **[Host bootstrap](03-host-bootstrap.md)** |
| Guided **`curl`** proofs | **[Quickstarts](05-quickstarts.md)** |

Deep protocol tables remain in **[HTTP API](../reference/01-http-api-reference.md)**—finish **Learn 101** before living there permanently.

## Executive capsule

**Outcome:** explain Fleet to another engineer without opening **`fleet_server/main.py`**. Maturity: **demonstrated**.

## Who this is for

Operators and delivery leads at the **discover** stage. Skim the executive capsule first; agents should respect the page frontmatter contract.

## Evidence and maturity

Maturity: **demonstrated**. Statements here reflect the owning repo (`forge-fleet`) at `last_reviewed`; treat anything not explicitly marked as demonstrated as design direction rather than a shipped guarantee.

## Trust boundary

Forge keeps humans in charge of promotion, approval, and release decisions; automation proposes and executes only within approved boundaries described here.
