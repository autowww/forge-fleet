# Examples — Workspace upload

Tarball handshake (**`workspace_upload_required`**) details stay in **[Workspace upload](../build-201/01-workspace-upload.md)** — includes manifest knobs + **`PUT`** sizing caveats.

For copy-paste **`curl`** transcripts and sizing tables, use **[Examples & recipes](../build-201/05-examples-and-recipes.md)** (workspace flows) and the **[jobs](jobs.md)** + **[curl](curl.md)** pages for auth patterns.

## Purpose

Point implementers at the workspace tarball handshake (**`workspace_upload_required`**) and manifest rules.

## Prerequisites

Job created with workspace metadata; **`docker`** / size limits understood per Build 201.

## Copy-paste steps

Follow **[Workspace upload](../build-201/01-workspace-upload.md)** and long-form **`curl`** in **[Examples & recipes](../build-201/05-examples-and-recipes.md)**.

## Expected output

After **`PUT /v1/jobs/{id}/workspace`**, JSON includes **`workspace_state: ready`** and the job transitions from **queued**.

## Error handling

**400** **`extract_failed`**, **409** when not **queued** / already uploaded—see **[error-handling.md](error-handling.md)**.

## Security notes

Tarballs are extracted on the host; keep archives free of path-escape payloads (see manifest schema).

## Related

- **[HTTP API](../reference/01-http-api-reference.md)** (**`uploadJobWorkspace`**)
- **`workspace-manifest.schema.json`**

## Validation status

- Example manifest: **[`payloads/valid/workspace-manifest.json`](payloads/valid/workspace-manifest.json)**; invalid path example: **`payloads/invalid/workspace-manifest.invalid.bad-path.json`** (**`check-schema-examples.py`**).
- OpenAPI documents binary **`requestBody`** for **`PUT /v1/jobs/{id}/workspace`**: **[`../schemas/openapi.json`](../schemas/openapi.json)**.
