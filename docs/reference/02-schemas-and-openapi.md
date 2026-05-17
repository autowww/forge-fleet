# Forge Fleet machine-readable schemas

Documentation and test-time artifacts (not enforced at HTTP runtime). Use with OpenAPI clients, Cursor, or CI validation.

**Worked examples** — see [`docs/examples/payloads/valid/`](../examples/payloads/valid/) (validated against sibling `*.schema.json` via **`scripts/check-schema-examples.py`**) and **`docs/examples/payloads/invalid/*.invalid.*.json`** (must fail validation for the named schema).

**Published copies** — On the public handbook (`fleet.forgesdlc.com`), JSON files are served under **`/schemas/`** (same names as in this repository: [`docs/schemas/`](../schemas/)).

| File | Purpose | Code / routes |
|------|-----------|----------------|
| **[openapi.json](../schemas/openapi.json)** | OpenAPI 3.1 — every HTTP route | [`fleet_server/main.py`](../../fleet_server/main.py); keep in sync via [`scripts/check-docs-contracts.py`](../../scripts/check-docs-contracts.py) |
| **[workspace-manifest.schema.json](../schemas/workspace-manifest.schema.json)** | `.forge_workspace_manifest.json` inside workspace tarballs | [`fleet_server/workspace_bundle.py`](../../fleet_server/workspace_bundle.py); **`PUT /v1/jobs/{id}/workspace`** |
| **[requirement-templates.schema.json](../schemas/requirement-templates.schema.json)** | `etc/containers/requirement_templates.json` | [`fleet_server/container_templates.py`](../../fleet_server/container_templates.py); **`GET`/`PUT /v1/container-templates`** |
| **[container-types.schema.json](../schemas/container-types.schema.json)** | `etc/containers/types.json` | [`fleet_server/container_layout.py`](../../fleet_server/container_layout.py); **`GET`/`PUT /v1/container-types`** |
| **[build-cache.schema.json](../schemas/build-cache.schema.json)** | `etc/containers/build_cache.json` | [`fleet_server/container_templates.py`](../../fleet_server/container_templates.py); surfaced in **`GET /v1/container-templates/status`** |
| **[container-service.schema.json](../schemas/container-service.schema.json)** | `etc/services/*.json` | [`fleet_server/container_layout.py`](../../fleet_server/container_layout.py); container-services API |
| **[job-create-request.schema.json](../schemas/job-create-request.schema.json)** | **`POST /v1/jobs`** body | [`fleet_server/main.py`](../../fleet_server/main.py) |
| **[job-response.schema.json](../schemas/job-response.schema.json)** | **`GET /v1/jobs/{id}`** response (subset) | Redacts secrets from stored meta in handler |
| **[health-response.schema.json](../schemas/health-response.schema.json)** | **`GET /v1/health`** | Host metrics + version |
| **[telemetry-response.schema.json](../schemas/telemetry-response.schema.json)** | **`GET /v1/telemetry`** | Historical samples |
| **[admin-snapshot-response.schema.json](../schemas/admin-snapshot-response.schema.json)** | **`GET /v1/admin/snapshot`** | Large dashboard payload |
| **[cooldown-event-create-request.schema.json](../schemas/cooldown-event-create-request.schema.json)** | **`POST /v1/cooldown-events`** | |
| **[cooldown-summary-response.schema.json](../schemas/cooldown-summary-response.schema.json)** | **`GET /v1/cooldown-summary`** | |
| **[version-response.schema.json](../schemas/version-response.schema.json)** | **`GET /v1/version`** | |
| **[host-operator-steps.schema.json](../schemas/host-operator-steps.schema.json)** | Shape of [`host-operator-steps.json`](../host-operator-steps.json) | Human-maintained operator notes only |

## Examples

**Valid workspace manifest** (excerpt):

```json
{
  "schema_version": 1,
  "files": [
    {
      "path": "src/main.py",
      "size": 120,
      "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    }
  ]
}
```

Use a SHA-256 that matches the file content after extraction; the line above is an example digest format.

**Invalid**: missing `files`, absolute `path`, or wrong `schema_version`.

Run the contract checker from the repo root:

```bash
python3 scripts/check-docs-contracts.py
```

## See also

- **[API-REFERENCE.md](01-http-api-reference.md)** — Canonical route + auth table
- **[EXAMPLES.md](../build-201/05-examples-and-recipes.md)** — curl recipes
