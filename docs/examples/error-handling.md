# Examples — HTTP error cookbook

| Status | Typical meaning | Recover |
|--------|-----------------|--------|
| **401 / 403** | Bearer missing/wrong vs bind policy | **[Security](../operate-301/01-security.md)** |
| **404** | Unknown job id / typo'd URL | Confirm **`GET /v1/jobs/{id}`** spelling |
| **409** | Service delete/in-use conflicts | Inspect JSON **`detail`** |
| **413** | Workspace tarball oversize | Tune **`FLEET_WORKSPACE_UPLOAD_MAX_BYTES`** (**[Configuration](../reference/03-configuration-and-env.md)**) |
| **400** invalid payload | Schema mismatch | Diff body vs **`job-create-request.schema.json`** |

Always capture **`curl -i`** when filing bugs—redact tokens first.

## Purpose

Symptom-first HTTP status map for Fleet clients.

## Prerequisites

Know **`BASE`**, auth mode, and whether requests hit Fleet directly or through a proxy.

## Copy-paste steps

Use this table while reading JSON **`error`** / **`detail`** fields from responses.

## Expected output

Actionable next steps (rotate token, fix tarball size, fix schema).

## Error handling

This page *is* the error handling index; pair with **[Operate 301 — Troubleshooting](../operate-301/04-troubleshooting.md)**.

## Security notes

Redact bearer tokens and host paths before posting logs publicly.

## Related

- **[Operate 301 — Security](../operate-301/01-security.md)**
- **`job-create-request.schema.json`**

## Validation status

- Invalid fixtures **[`payloads/invalid/job-create-request.invalid.missing-argv.json`](payloads/invalid/job-create-request.invalid.missing-argv.json)** prove schema rejection in CI.
- OpenAPI error model: **`ErrorJson`** in **[`../schemas/openapi.json`](../schemas/openapi.json)**.
