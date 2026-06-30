# Fleet Apps Extension Protocol (FAEP v1)

Fleet can install **apps** — zip packages published on `fleet.forgesdlc.com` — that extend the operator admin with declarative UI, server-side data handlers, and an in-package documentation wiki.

## Mental model

| Layer | Role |
|-------|------|
| **Public catalog** | `catalog/catalog.json` + handbook pages describe available packages and download URLs. |
| **Package zip** | Manifest, UI spec, Python handlers, operator docs, optional wheel. |
| **Fleet host** | Installs packages under `{data-dir}/apps/{id}/{version}/`, registers `etc/fleet-apps/{id}.json`, serves admin tabs and APIs. |
| **Kitchen Sink** | `forge-fleet-app-ui.js` renders `ui/app.ui.json` widgets against Fleet data/action endpoints. |

Apps are **not** arbitrary iframe HTML in v1. UI is schema-driven; behavior is implemented in named Python handlers shipped with the package.

## Dual wiki

1. **In-package wiki** — `docs/**/*.md` inside the zip (operator/dev reference).
2. **Runtime mirror** — Fleet renders those files at `/admin/apps/{app_id}/docs/{slug}.html` with the same admin chrome.
3. **Public handbook page** — `fleet-app.page.md` in the package becomes a catalog page on `fleet.forgesdlc.com` when published.

## Package layout

```
fleet-app.manifest.json
ui/app.ui.json
docs/README.md
fleet-app.page.md
dist/*.whl                    # optional
```

See JSON Schema: [`fleet-app-manifest.schema.json`](../schemas/fleet-app-manifest.schema.json).

## Install flow

1. Fleet fetches [`catalog/catalog.json`](https://fleet.forgesdlc.com/catalog/catalog.json) (override with `FLEET_APPS_CATALOG_URL`).
2. Operator calls `POST /v1/fleet-apps/install` with `app_id` and optional `version`.
3. Fleet downloads the zip, verifies **SHA-256**, extracts, `pip install`s the wheel when present.
4. Fleet writes `etc/fleet-apps/{id}.json` and exposes the app in `/admin/` snapshot `apps[]`.

## Security (v1)

- Catalog downloads must use **HTTPS**; hash verification is mandatory.
- Handler modules declare **permissions**; Fleet rejects unknown permissions.
- Mutating routes require bearer auth when Fleet auth is enforced.
- Docs mirror paths are confined to the installed package `docs/` tree.

## Pilot app

**[forge-cdp-manager](https://github.com/autowww/forge-cdp-manager)** — CDP surface lease inspection and stale reclaim from Fleet admin.

## See also

- **[Fleet Apps API](../reference/04-fleet-apps-api.md)**
- **[Fleet Apps publishing](../maintainers/04-fleet-apps-publishing.md)**
- **[Apps catalog hub](../apps/README.md)**
