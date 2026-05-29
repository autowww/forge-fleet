# OpenAPI path fragments

Each file lists every route whose first path segment after `/v1/` matches the filename (or `admin` for `/admin…` routes). Regenerate the deploy bundle from the parent folder:

```bash
python3 scripts/bundle_openapi.py
```

| File | Routes (prefix) |
|------|-----------------|
| `admin.json` | `/admin`, `/admin/`, static admin assets |
| `container-services.json` | `/v1/container-services` |
| `container-templates.json` | `/v1/container-templates` |
| `container-types.json` | `/v1/container-types` |
| `containers.json` | `/v1/containers` |
| `cooldown-events.json` | `/v1/cooldown-events` |
| `cooldown-summary.json` | `/v1/cooldown-summary` |
| `health.json` | `/v1/health` |
| `jobs.json` | `/v1/jobs` (create, workspace upload, workspace worker) |
| `services.json` | `/v1/services` (legacy forge-llm helpers) |
| `telemetry.json` | `/v1/telemetry` |
| `templates.json` | `/v1/templates` |
| `version.json` | `/v1/version` |
