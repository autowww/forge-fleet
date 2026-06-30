# Fleet Apps HTTP API

FAEP v1 routes exposed by `fleet_server`. JSON Schemas live under [`schemas/`](../schemas/). OpenAPI: [`openapi.json`](../schemas/openapi.json).

## Auth

All `/v1/fleet-apps/*` routes follow the same bearer policy as other `/v1/*` routes. `/admin/apps/*` static and docs mirror routes are served without bearer (same as `/admin/`).

## Routes

| Method | Path | Notes |
|--------|------|--------|
| GET | `/v1/fleet-apps/catalog` | Remote published catalog (`FLEET_APPS_CATALOG_URL`). |
| GET | `/v1/fleet-apps/installed` | Installed apps on this host (`etc/fleet-apps/`). |
| POST | `/v1/fleet-apps/install` | Body `app_id`, optional `version`, optional `catalog_url`. |
| POST | `/v1/fleet-apps/install-local` | Body omitted; raw zip body; optional `X-Fleet-App-Sha256` header. |
| DELETE | `/v1/fleet-apps/{id}` | Uninstall app record and remove install tree. |
| GET | `/v1/fleet-apps/{id}/ui` | Resolved `ui/app.ui.json` from installed package. |
| GET | `/v1/fleet-apps/{id}/data/{binding}` | Execute named data handler; returns JSON for UI widgets. |
| POST | `/v1/fleet-apps/{id}/actions/{action}` | Execute named action handler; JSON body optional. |
| GET | `/admin/apps/{id}/` | Minimal host page mounting `ForgeFleetAppUi`. |
| GET | `/admin/apps/{id}/docs/` | Redirect to docs index. |
| GET | `/admin/apps/{id}/docs/{slug}` | Rendered in-package markdown (`.html` suffix optional). |

## Install request

```json
{
  "app_id": "forge-cdp-manager",
  "version": "0.1.0"
}
```

Response:

```json
{
  "ok": true,
  "id": "forge-cdp-manager",
  "version": "0.1.0",
  "install_path": "/var/lib/forge-fleet/apps/forge-cdp-manager/0.1.0"
}
```

## UI data binding

`GET /v1/fleet-apps/forge-cdp-manager/data/leases` returns:

```json
{
  "ok": true,
  "rows": [
    {
      "surface": "outlook_mail",
      "cdp_url": "http://127.0.0.1:9222",
      "owner": "sync-1",
      "pid": 12345,
      "holder_alive": true,
      "expired": false
    }
  ]
}
```

## Action example

`POST /v1/fleet-apps/forge-cdp-manager/actions/release_stale`

```json
{ "force": true }
```

## Snapshot

`GET /v1/admin/snapshot` includes `apps[]`:

```json
{
  "id": "forge-cdp-manager",
  "title": "Forge CDP Manager",
  "version": "0.1.0",
  "enabled": true,
  "docs_index": "/admin/apps/forge-cdp-manager/docs/"
}
```

## Environment

| Variable | Default | Meaning |
|----------|---------|---------|
| `FLEET_APPS_CATALOG_URL` | `https://fleet.forgesdlc.com/catalog/catalog.json` | Published catalog index. |
| `FLEET_APP_PACKAGE_MAX_BYTES` | `67108864` | Max zip size for install-local. |

## See also

- **[Fleet Apps protocol](../build-201/03-fleet-apps-protocol.md)**
- **[HTTP API reference](01-http-api-reference.md)**
