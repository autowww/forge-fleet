# Reference

**Purpose:** authoritative **HTTP**, **schema**, and **configuration** lookups while building or operating Fleet.

**Find quickly:** **[HTTP API](01-http-api-reference.md)** (routes + bearer matrix) · **[Schemas & OpenAPI](02-schemas-and-openapi.md)** (mirrored to Hosting **`/schemas/`**) · **[Configuration](03-configuration-and-env.md)**.

| | |
| --- | --- |
| **Audience** | Integrators, client authors, operators verifying payloads |
| **Effort** | **~1–2 hours** first read; then use as a catalog |
| **Prerequisites** | Skim **[Learn 101](../learn-101/README.md)** so vocabulary (**`docker_argv`**, **`meta`**, tokens) is familiar |
| **Success** | You can point to the exact route + schema for each call you make |

| Page | Covers |
|------|--------|
| **[HTTP API (v1)](01-http-api-reference.md)** | Every `/v1/*`, `/admin/*` static asset, bearer matrix |
| **[Schemas & OpenAPI](02-schemas-and-openapi.md)** | `docs/schemas/openapi.json` + sibling JSON schemas (mirrored to Hosting **`/schemas/`**) |
| **[Configuration](03-configuration-and-env.md)** | Environment knobs + defaults |
| **[Forge LCDL relationship](04-forge-lcdl-relationship.md)** | How Fleet compares to **`forge-lcdl`** governed LLM |
| **[Workspace localization scope](05-workspace-localization-scope.md)** | SKU / locale stance for workspaces |

**Before:** **[Operate 301](../operate-301/README.md)** · **Examples:** **[Examples hub](../examples/README.md)**
