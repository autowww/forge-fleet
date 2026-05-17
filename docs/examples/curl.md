# Examples — curl conventions

Fleet examples assume:

```bash
export BASE=http://127.0.0.1:18765   # no trailing slash; never append /v1 here
export FLEET_TOKEN=                    # optional on loopback-only dev servers
curl_auth=( )
[[ -n "${FLEET_TOKEN:-}" ]] && curl_auth=( -H "Authorization: Bearer ${FLEET_TOKEN}" )
```

Then:

```bash
curl -sS "${curl_auth[@]}" "${BASE}/v1/version"
curl -sS "${curl_auth[@]}" "${BASE}/v1/health"
```

Deep dives ( **`jq`**, **`POST /v1/jobs`**, **`git-self-update`**, dispose helpers): **[Examples & recipes](../build-201/05-examples-and-recipes.md)**.

## Purpose

Standard **`BASE`**, **`FLEET_TOKEN`**, and **`curl_auth`** arrays for all Fleet copy-paste examples.

## Prerequisites

**`curl`** and a reachable Fleet HTTP endpoint.

## Copy-paste steps

Export **`BASE`** without a trailing slash; conditionally set bearer headers as shown above.

## Expected output

**`GET /v1/version`** and **`GET /v1/health`** return JSON with **`ok: true`** (see respective schema files under **`docs/schemas/`**).

## Error handling

Use **`curl -i`**; map status codes via **[error-handling.md](error-handling.md)**.

## Security notes

Do not echo tokens into shared logs; prefer env vars and shell history controls.

## Related

- **[Examples & recipes](../build-201/05-examples-and-recipes.md)**
- **[HTTP API](../reference/01-http-api-reference.md)**

## Validation status

- Example snippets are scanned by **`scripts/check-docs-examples.py`**.
- Contracts: **`scripts/check-openapi-quality.py`**, **`scripts/check-schema-examples.py`** (payload fixtures), **[`../schemas/openapi.json`](../schemas/openapi.json)**.
