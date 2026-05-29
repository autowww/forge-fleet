# Fleet JSON schemas

Machine-readable contracts for HTTP payloads and on-disk config shapes. Narrative context: [Schemas & OpenAPI](../reference/02-schemas-and-openapi.md).

## OpenAPI (HTTP surface)

| Path | Role |
|------|------|
| [`openapi/`](openapi/) | **Source of truth** — `openapi-root.json`, `components.json`, `paths/*.json` by API area |
| [`openapi.json`](openapi.json) | **Generated bundle** — run `python3 scripts/bundle_openapi.py` before deploy or docs CI |

Edit fragments only; do not hand-edit the bundle (it is gitignored and excluded from code-footprint scans).

## Sibling `*.schema.json` files

JSON Schema documents referenced from OpenAPI (`#/components/schemas/…`) and used by `scripts/check-schema-examples.py`. One file per payload or config shape; names match the stem in `$ref` links inside `openapi/components.json`.
