# Forge LCDL and Forge Fleet

**Forge Fleet** and **Forge LCDL** solve different layers of the Forge workspace:

| Concern | **Forge Fleet** | **Forge LCDL** (`forge-lcdl`, package **`forge_lcdl`**) |
|--------|-----------------|-------------------------------------------------------|
| Role | Small **HTTP + bearer** service that **queues Docker argv jobs**, exposes **`/v1/*`**, **`/admin/`**, telemetry, cooldown accounting, managed compose services | **Private Python library** for **synchronous**, **governed** OpenAI-compatible **`chat/completions`** tasks: **`run_task`**, contracts, **`Result`**, generic JSON/transport helpers, operators |
| Where it runs | Host process + Docker (orchestration) | **Imported** into consumer Python processes (CLI, Flask apps, notebooks, Fleet container images **if** the image installs that dependency) |
| Typical callers | Forge Lenses (Docs Health), scripts using **`curl`** **`POST /v1/jobs`**, admin UI | **forge-certificators** source-ingest (**`pw_*`** tasks, Phase A routing), benchmarks, MCP examples |

Fleet **does not** ship LCDL prompts or **`run_task`** on its HTTP surface. Conversely, LCDL **does not** enqueue Docker workloads or authenticate Fleet bearer tokens — any container that happens to **`pip install forge-lcdl`** still uses **that process’s** `LLM_*` / gateway configuration (often aligned with Certificator or workbench docs), not Fleet’s **`FLEET_BEARER_TOKEN`**.

Docs Health **`session_step`** jobs may execute in Fleet-managed containers whose **Dockerfile** installs consumers (e.g. tooling that **`pip install`'s **`forge-certificators`** and thus **`forge-lcdl`**). That coupling is **per image** / **`pyproject.toml`**, not a dedicated Fleet API.

## Observability crossover

Fleet records **LLM thermal / cooldown waits** (**`POST /v1/cooldown-events`**, **`/v1/cooldown-summary`**) after clients decide to sleep; certificators and LCDL-bearing scripts are common emitters when they share Granite-style hosts with Fleet. Interpret those metrics as **orchestration + host policy**, not as “Fleet vs LCDL” protocol.

## Handbook

Canonical **Forge LCDL** handbook (Firebase Hosting project **`lcdl-542d8`**) is built from the **`forge-lcdl`** Markdown tree via **`forge-lcdl-website`**. Narrative onboarding: **`docs/WHAT-IS-LCDL.md`** in **`forge-lcdl`**. **Forge Fleet** handbook (Firebase project **`fleet-2f1d3`**) stays **`forge-fleet-website`**.
