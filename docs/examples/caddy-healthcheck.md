# Examples — Caddy TLS health probe

Once **[Caddy + systemd](../build-201/03-caddy-systemd.md)** terminates TLS:

```bash
export BASE=https://fleet.example.com
curl -fsS "${curl_auth[@]}" "${BASE}/v1/health"
```

`-f` surfaces HTTP errors immediately—combine with **`systemd`** **`ExecStartPost=/usr/bin/curl …`** cautiously (avoid thundering herds).

Unified Granite hostname nuances → **[Caddy unified Granite](../build-201/04-caddy-unified-granite.md)**.

## Purpose

Health-check **`curl`** through a TLS front-end (**Caddy**) with fail-fast **`-f`**.

## Prerequisites

Caddy reverse proxy configured per **[Caddy + systemd](../build-201/03-caddy-systemd.md)**; **`BASE`** uses **`https://`**.

## Copy-paste steps

Export **`BASE`** to the public hostname; reuse **`curl_auth`** from **[curl.md](curl.md)** when bearer auth is on.

## Expected output

**`GET /v1/health`** returns **200** JSON; **`-f`** maps non-2xx to shell failure for probes.

## Error handling

**502** often means upstream Fleet unreachable—compare direct loopback **`curl`** vs through the proxy.

## Security notes

Terminate TLS at the edge; keep **`FLEET_BEARER_TOKEN`** out of unit files when **`EnvironmentFile`** is preferred.

## Related

- **[Caddy + systemd](../build-201/03-caddy-systemd.md)**
- **[HTTP API](../reference/01-http-api-reference.md)**

## Validation status

- **`check-docs-examples.py`** scans docs for **`curl`** patterns; health payload shape in **`health-response.schema.json`** + fixture **`payloads/valid/health-response.json`**.
