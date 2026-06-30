# Fleet Apps publishing

Use this checklist before publishing a FAEP package to `fleet.forgesdlc.com`.

## Prerequisites

- Package built with `scripts/build-fleet-app.sh` in the app repo.
- `fleet-app.page.md` frontmatter matches [`fleet-app-manifest.schema.json`](../schemas/fleet-app-manifest.schema.json).
- `ui/app.ui.json` validates against [`fleet-app-ui-v1.schema.json`](../schemas/fleet-app-ui-v1.schema.json).

## Publish (forge-fleet-website)

From **`forge-fleet-website`**:

```bash
./scripts/publish-fleet-app.sh \
  --package /path/to/app/dist/forge-cdp-manager-0.1.0.fleet-app.zip
```

With deploy:

```bash
./scripts/publish-fleet-app.sh \
  --package /path/to/app/dist/forge-cdp-manager-0.1.0.fleet-app.zip \
  --deploy
```

The script:

1. Validates the zip layout and schemas.
2. Copies the zip to `website/packages/`.
3. Updates `forge-fleet/docs/apps/{id}/page.md` and `catalog/catalog.json` in the submodule.
4. Runs `python3 generator/build-site.py`.
5. Optionally deploys Firebase hosting.

## Git workflow

1. Commit catalog + handbook changes in **`forge-fleet`**.
2. Bump **`forge-fleet`** submodule pointer in **`forge-fleet-website`**.
3. Commit built `website/` output in **`forge-fleet-website`**.

## Verify

- `https://fleet.forgesdlc.com/catalog/catalog.json` lists the app with correct `sha256`.
- Handbook page renders at the `handbook_page` slug.
- Zip downloads from `download_url`.
- Running Fleet can `POST /v1/fleet-apps/install` successfully.

## See also

- **[Fleet Apps protocol](../build-201/03-fleet-apps-protocol.md)**
- **[Apps catalog](../apps/README.md)**
