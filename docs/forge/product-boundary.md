# Fleet Product Boundary

## Owns

- controlled Docker execution
- job templates
- job state
- logs
- telemetry
- runtime artifacts

## Does not own

- planning
- LLM reasoning
- approval authority
- canonical policy

## Consumes

- `fleet_template.v1`
- `approval_request.v1`
- `forge_run_id` metadata

## Emits

- `fleet_job_summary.v1`
- telemetry/artifact refs
