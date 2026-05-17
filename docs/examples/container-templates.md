# Examples — Container templates

Requirement-template builds (**`POST /v1/container-templates/build`**) & cache semantics → **[Container templates](../build-201/02-container-templates.md)**.

Use **`GET /v1/container-templates/status`** after triggering builds; JSON schemas live beside **`docs/schemas/requirement-templates.schema.json`**.

## Purpose

Link requirement-template builds, cache inspection, and schema contracts.

## Prerequisites

Fleet with container layout initialized; auth per **[curl.md](curl.md)**.

## Copy-paste steps

Use Build 201 **[Container templates](../build-201/02-container-templates.md)** for **`curl`** transcripts and **`POST /v1/container-templates/build`** flows.

## Expected output

**`status`** returns **`build_cache`** / **`build_state`** JSON; **`PUT …/package`** accepts a template tarball per OpenAPI **`putContainerTemplatePackage`**.

## Error handling

Inspect **`400`** / **`409`** JSON from resolve/build endpoints; see **[error-handling.md](error-handling.md)**.

## Security notes

Template archives are extracted server-side—only upload trusted packages.

## Related

- **`requirement-templates.schema.json`** · **`build-cache.schema.json`**
- **[HTTP API](../reference/01-http-api-reference.md)**

## Validation status

- Response subsets are covered in **[`../schemas/openapi.json`](../schemas/openapi.json)** (**`ContainerTemplatesStatusResponse`**, **`TemplatePackageUploadResponse`**).
- CI: **`check-openapi-quality.py`**, **`check-docs-contracts.py`**.
