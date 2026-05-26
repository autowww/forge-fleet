---
description: Bounded container jobs on hosts you operate—token-gated HTTP APIs, streamed logs, SQLite job history, optional /admin. For Forge Lenses, CI, scripts, and runbooks.
---

# Run container jobs on infrastructure you own

<p>Run bounded container jobs on hosts you operate through a token-gated HTTP control plane with streamed logs, SQLite history, and optional operator UI. Fleet is not a multi-cluster scheduler.</p>

<p class="mb-3 forge-readme-mechanism-line">Under the hood it is a <strong>token-gated HTTP control plane</strong> for <code>docker_argv</code> jobs on <strong>hosts you operate</strong>, with an optional <code>/admin</code> surface. Call it from <strong>Forge Lenses</strong>, CI, scripts, and runbooks.</p>

<div class="forge-fleet-product-home">

<div class="d-flex flex-wrap gap-2 align-items-center my-3">
<a class="btn btn-forge" href="docs/learn-101/02-install-run-local-dev.md">Get started</a>
<a class="btn forge-home-secondary-cta" href="docs/start/01-start-here.md">View docs</a>
</div>

```blueprint-diagram-ascii
key: linear
alt: Fleet job flow from client through HTTP API, SQLite ledger, and Docker runner to log polling
caption: Bearer-authenticated clients submit docker_argv jobs; Fleet persists state in SQLite and runs containers on the host you operate.
Client -> Fleet API -> SQLite -> Docker runner -> logs -> Poll GET job
```

<p class="lead mb-0">Choose an entry path—depth stays one click away in Learn, Start, and Reference. <a href="#how-fleet-works">How it works</a> on one screen, then dive into docs when you need precision.</p>

<div class="row row-cols-1 row-cols-md-3 g-3 my-5">
<div class="col">
<div class="forge-callout forge-callout-surface h-100">
<h2 class="h6 mt-0">Prove it on a workstation</h2>
<p class="small mb-0">Install locally, run your first container-backed job, and confirm logs and history behave the way operators expect.</p>
</div>
</div>
<div class="col">
<div class="forge-callout forge-callout-surface h-100">
<h2 class="h6 mt-0">Service one production host</h2>
<p class="small mb-0">Bootstrap OS dependencies, install from git, and wire TLS or reverse proxies using the production-oriented guides.</p>
</div>
</div>
<div class="col">
<div class="forge-callout forge-callout-surface h-100">
<h2 class="h6 mt-0">Automate with clear contracts</h2>
<p class="small mb-0">Call Fleet from scripts, CI, or Studio-style integrations—then deepen on schemas and examples when you need precision.</p>
</div>
</div>
</div>

</div>

## How Fleet works

Staged workflow for a typical job—from an authenticated request to reviewable evidence:

1. **Authenticate** — Callers use a **bearer token** on Fleet’s HTTP surface; operators set policy and storage roots in **[Configuration](docs/reference/03-configuration-and-env.md)** and **[Security](docs/operate-301/01-security.md)**.
2. **Submit work** — Jobs are accepted as **docker_argv** payloads on versioned **`/v1/*`** routes (see **[HTTP API reference](docs/reference/01-http-api-reference.md)**).
3. **Stream evidence** — **stdout/stderr** and completion status are visible to operators and integrating tools during the run.
4. **Review history** — Runs are recorded in **SQLite** with metadata for audit-friendly review; day-two operations in **[Operations runbook](docs/operate-301/02-operations-runbook.md)**.

## Pick your path

- **First-time operator** — start in [Learn 101](docs/learn-101/README.md) (what Fleet is, local install, first job, dashboard tour).
- **Existing host** — jump to [Host bootstrap](docs/learn-101/03-host-bootstrap.md) and [Git install](docs/learn-101/04-git-install.md), then the [Operate 301](docs/operate-301/README.md) runbook when you are ready for production posture.

## How Fleet sits in Forge

Forge positions Fleet as **controlled execution** alongside methodology, workspace visibility, governed LLM work, and shared practice artifacts:

- **[Forge SDLC](https://forgesdlc.com/)** — methodology, workspace visibility, governed reasoning, controlled execution, and shared practice—how Fleet fits in the broader Forge landscape (public overview).
- **[Forge Lenses / Studio](docs/examples/lenses-studio.md)** — typical callers for bounded jobs and health integrations.
- **[Forge LCDL and Fleet](docs/reference/04-forge-lcdl-relationship.md)** — where governed synchronous tasks meet Fleet’s HTTP surface.
- **Blueprints methodology pack** — vendored **`blueprints`** submodule with Cursor/setup templates.
  - **[Submodule workflow](docs/start/03-repository-companion.md#submodules-blueprints--kitchensink)**
  - **[Blueprints handbook](https://blueprints.forgesdlc.com/)**

## Designed for governed adoption

Concrete adoption boundaries—the items reviewers expect articulated up front:

- **Data boundary —** SQLite and artefacts stay inside the Fleet data roots you provision; cite **[Security](docs/operate-301/01-security.md)** for storage and token posture claims.
- **Execution boundary —** argv-driven Docker jobs run on **that Fleet host’s socket** unless you deliberately integrate something else upstream; cite **[Architecture](docs/operate-301/03-architecture.md)** for component layering.
- **Human and operator controls —** tokens, bearer policy, scripted upgrades, and remote refresh flows appear in **[Configuration](docs/reference/03-configuration-and-env.md)** and **[Upgrade & remote ops](docs/operate-301/05-upgrade-release-and-remote-update.md)**.
- **Evidence and review —** job history plus streamed logs underpin audit-friendly operator reviews; deepen with **[Operate 301 — Operations runbook](docs/operate-301/02-operations-runbook.md)** when needed.
- **Admin surfaces —** the **`/admin`** area is optional and oriented around operator visibility of jobs and configuration; treat it as part of your operational access model, not a multi-tenant SaaS console.
- **Not a replacement for orchestrators** — Fleet is not positioned as Kubernetes-style multi-tenant scheduling; keep multi-cluster expectations out-of-scope unless your deployment guide explicitly covers them ([repository companion limitations](docs/start/03-repository-companion.md)).

## Operator-ready depth

Need endpoint tables, environment matrices, or install scripts first? Use the **[HTTP API reference](docs/reference/01-http-api-reference.md)** and **[Repository companion](docs/start/03-repository-companion.md)**—the overview above stays short on purpose.
