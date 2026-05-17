# Examples — Managed services (`forge_llm`)

Lifecycle verbs (**`/v1/container-services/*`**):

```bash
curl -sS "${curl_auth[@]}" "${BASE}/v1/container-services"          # list
curl -sS "${curl_auth[@]}" -X POST "${BASE}/v1/container-services" \
  -H 'Content-Type: application/json' -d @service.json               # register
curl -sS "${curl_auth[@]}" -X POST "${BASE}/v1/container-services/default/start"
curl -sS "${curl_auth[@]}" -X POST "${BASE}/v1/container-services/default/stop"
```

Replace **`default`** with your **`etc/services/*.json`** id. Legacy aliases **`/v1/services/forge-llm/*`** remain documented in **[HTTP API](../reference/01-http-api-reference.md)**.

Auth helpers: **[curl.md](curl.md)**.

## Purpose

Show **`container-services`** list/register/start/stop **`curl`** shapes and legacy **`forge-llm`** aliases.

## Prerequisites

**`service.json`** matching **`container-service.schema.json`**; **`BASE`** / token per **[curl.md](curl.md)**.

## Copy-paste steps

Substitute a real service id for **`default`** before running start/stop.

## Expected output

**`GET /v1/container-services`** returns **`services`** array and **`paths`** hints; start/stop return JSON acks.

## Error handling

**404** if id unknown; **`502`** / **`503`** when compose/docker unavailable—see **[Operate 301](../operate-301/02-operations-runbook.md)**.

## Security notes

Compose roots and env files live on the Fleet host; restrict filesystem permissions.

## Related

- **[HTTP API](../reference/01-http-api-reference.md)**
- **`container-service.schema.json`**

## Validation status

- **`container-service.schema.json`** defines on-disk record shape; OpenAPI **`ContainerServicesListResponse`** covers list payloads (**[`../schemas/openapi.json`](../schemas/openapi.json)**).
