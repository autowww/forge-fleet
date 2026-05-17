# Examples — Telemetry + host health

| Goal | Endpoint |
|------|-----------|
| Tiny heartbeat JSON | **`GET /v1/health`** |
| Buffered telemetry waveforms | **`GET /v1/telemetry?minutes=…`** |
| Operator bundles | **`GET /v1/admin/snapshot`** |
| Cooldown accounting | **`GET /v1/cooldown-summary`** |

Sample **`curl`** + **`jq`** filters live in **[Examples & recipes](../build-201/05-examples-and-recipes.md)**.

## Purpose

Map observability endpoints (**health**, **telemetry**, **snapshot**, **cooldown-summary**) to outcomes.

## Prerequisites

Bearer auth when required; understand **`period`** query params for time windows.

## Copy-paste steps

Reuse filters from **[Examples & recipes](../build-201/05-examples-and-recipes.md)** for **`curl`** + **`jq`**.

## Expected output

**`GET /v1/telemetry`** returns **`samples`** arrays per **`telemetry-response.schema.json`** subset; **`/v1/health`** matches **`health-response.schema.json`**.

## Error handling

**400** when **`period`** is missing/invalid—response JSON lists allowed periods.

## Security notes

**`/v1/admin/snapshot`** is operator-grade; protect bearer tokens accordingly.

## Related

- **`telemetry-response.schema.json`** · **`health-response.schema.json`** · **`cooldown-summary-response.schema.json`**
- **[HTTP API](../reference/01-http-api-reference.md)**

## Validation status

- Fixture **[`payloads/valid/health-response.json`](payloads/valid/health-response.json)** validates against **`health-response.schema.json`** in CI.
- OpenAPI refs: **`TelemetryResponse`**, **`AdminSnapshotResponse`** in **[`../schemas/openapi.json`](../schemas/openapi.json)**.
