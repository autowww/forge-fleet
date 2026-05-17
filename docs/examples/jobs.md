# Examples — Jobs lifecycle

Tutorial-grade narrative lives in **[Learn 101 — First job](../learn-101/06-first-fleet-job.md)**.

**Canonical `docker_argv` payload** (schema-checked): **[`payloads/valid/job-create-request.json`](payloads/valid/job-create-request.json)**.

Language shortcuts:

| Language | Example |
|---------|---------|
| **`curl`** | **[curl.md](curl.md)** + **[Examples & recipes](../build-201/05-examples-and-recipes.md)** |
| **Python** | **[python.md](python.md)** |
| **TypeScript** | **[typescript-fetch.md](typescript-fetch.md)** |

Contract tables: **[HTTP API](../reference/01-http-api-reference.md)** · **`job-create-request.schema.json`**.

## Purpose

Route readers to canonical **`docker_argv`** payloads and language-specific job examples.

## Prerequisites

Running Fleet and the env conventions from **[curl.md](curl.md)** (or linked language pages).

## Copy-paste steps

Use **[First job](../learn-101/06-first-fleet-job.md)** for a full walkthrough; this page links out rather than duplicating blocks.

## Expected output

**`POST /v1/jobs`** returns **201** with **`id`**, **`status`**, and **`ok: true`** (see OpenAPI **`createJob`**).

## Error handling

See **[error-handling.md](error-handling.md)** and job polling patterns in Learn 101.

## Security notes

Send **`Authorization: Bearer …`** when the listen address is not loopback-only or when **`FLEET_ENFORCE_BEARER`** applies.

## Related

- **[HTTP API](../reference/01-http-api-reference.md)**
- **[Schemas](../reference/02-schemas-and-openapi.md)**

## Validation status

- **[`payloads/valid/job-create-request.json`](payloads/valid/job-create-request.json)** is validated against **`job-create-request.schema.json`** in CI (**`scripts/check-schema-examples.py`**).
- **[`../schemas/openapi.json`](../schemas/openapi.json)** includes **`operationId`** **`createJob`** and **`getJob`** response schemas.
