# Doc-hydration docs-check job (Hydration v2)

Fleet is the **template-only execution rail** for documentation quality runs in
the Forge Hydration v2 pipeline: site build, link check, and scorecard jobs run
as `docker_argv` jobs against an approved requirement template — never as
ad-hoc host commands.

## Files

| File | Purpose |
|------|---------|
| `requirement-template.json` | Requirement template row set to install via `PUT /v1/container-templates` (or admin UI): `docs_check_worker`, pinned Python image. |
| `job-docs-check-request.json` | `POST /v1/jobs` payload: workspace-uploaded docs repo, template image injection, then build + link check + scorecard inside the container. |

## Flow

1. Install the requirement template once:

```bash
curl -sS -X PUT "$FLEET/v1/container-templates" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  --data @requirement-template.json
```

2. Submit the job (uses `meta.use_fleet_template_image` + `meta.requirements`,
   with `workspace_upload_required` so the docs repo snapshot is uploaded via
   `PUT /v1/jobs/{id}/workspace` — see `docs/build-201/01-workspace-upload.md`):

```bash
curl -sS -X POST "$FLEET/v1/jobs" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  --data @job-docs-check-request.json
```

3. Job stdout/artifacts include the build log, `link_report.json`, and the
   scorecard output — these attach to the ForgeRun evidence for the hydration
   cycle (`forge-platform/scripts/docs_scorecard.py` consumes them).

## Governance

- Template-only rail: the job image comes from the approved requirement
  template; the argv only selects which documented check scripts to run.
- Results are evidence, not decisions: promotion still requires the reviewer
  decision manifest in forge-platform.
