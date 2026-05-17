# Deployment verification — Fleet handbook

## When to run

After **`firebase deploy`** (or equivalent) for **`fleet.forgesdlc.com`**, run the live smoke script from a network-connected environment:

```bash
bash scripts/check-live-docs-site.sh https://fleet.forgesdlc.com
```

## Local static smoke (website repo)

From **`forge-fleet-website/`** after **`python3 generator/build-site.py`**:

```bash
python3 scripts/check-site-smoke.py
python3 scripts/check-site-ux.py
```

## Contract URLs

| Path | Purpose |
| --- | --- |
| `/` | Handbook home with **Learn 101 / Build 201 / Operate 301** markers |
| `/docs-learn-101-06-first-fleet-job.html` | First-job tutorial (**`docker_argv`**, HTTP **201**) |
| `/schemas/openapi.json` | Published OpenAPI (mirrors **`docs/schemas/openapi.json`** in **forge-fleet**); includes **`operationId`**, per-operation **`description`**, binary upload media types |
| `/schemas/*.schema.json` | Published JSON Schemas (e.g. **`job-create-request`**, **`workspace-upload-response`**) |

The **`check-live-docs-site.sh`** script probes the rows above (including **`uploadJobWorkspace`** and **`application/octet-stream`** inside OpenAPI).

## Ownership

- **Content** — **forge-fleet** `docs/` (submodule inside **forge-fleet-website**).
- **Build** — **`generator/build-site.py`** copies PNG + schema assets into **`website/`**.

## Troubleshooting

- **404 on deep pages** — confirm Hosting rewrite rules and that the HTML filenames emitted by forge-autodoc match CDN paths.
- **Stale OpenAPI** — rebuild website after bumping the **forge-fleet** submodule pointer; redeploy Hosting.

## Comparing git to production

Hostings does not expose git SHAs by default. Record **`publish-record.json`** from your workspace deploy script when available, or compare **`GET /schemas/openapi.json`** **`info.version`** with **`pyproject.toml`**.
