# Forge Fleet — job workspace upload (`PUT /v1/jobs/{id}/workspace`)

Optional **gzip-compressed tarball** staging for `docker_argv` jobs so workers do not rely on host bind-mounts of consumer repos.

## Flow

1. **`POST /v1/jobs`** with JSON body including `"meta": { "workspace_upload_required": true, … }`.  
   Fleet creates the job with `meta.workspace_state` set to `pending_upload` and **does not** call the runner until the workspace exists.

2. **`PUT /v1/jobs/{job_id}/workspace`** with the raw bytes of a **`.tar.gz`** file (`Content-Type: application/gzip` recommended).  
   Requires the same **bearer auth** as other Fleet admin APIs (unless loopback auth skip applies).

3. Fleet extracts the archive under `{--data-dir}/job-workspaces/{job_id}/extracted`, validates size/path limits for the chosen **`meta.workspace_profile`** (or **`meta.container_class`** mapping), sets `workspace_state` to `ready`, then **starts** the runner.

4. The runner injects **`-v {extracted_abs}:{container_mount}:ro`** after `docker … run` (mount path comes from the selected **`workspace_profile`**; built-in profiles use **`/workspace`**).  
   After the job reaches a terminal status, Fleet **deletes** the per-job workspace directory.

## Meta fields

| Field | Meaning |
|-------|---------|
| `workspace_upload_required` | If true, defer runner until `PUT …/workspace`. |
| `workspace_profile` | Selects limits and container mount path (built-in: **`large_workspace`**, **`generic`**, …). |
| `workspace_state` | `pending_upload` → `ready` after successful extract. |
| `workspace_sha256` | SHA-256 of the upload bytes (hex). |
| `workspace_upload_bytes` | Compressed upload size. |
| `workspace_uncompressed_bytes` | Sum of regular-file member sizes validated before extract. |

## Operator limits

- **`FLEET_WORKSPACE_UPLOAD_MAX_BYTES`** — max HTTP body for `PUT` (default 256 MiB).
- Startup GC (in `fleet_server.main`) removes stale dirs under `job-workspaces/` (orphan `job_id` or queued upload pending too long, default max age **7 days**).

## Security

Upload is **authenticated** like `POST /v1/jobs`. Tar extraction rejects absolute paths, `..`, and symlinks/hardlinks in the archive. Sandboxing untrusted code still requires tight **Docker** / **gVisor** / VM policy on the Fleet host; see project security guidance.

## Consumers

Any authenticated client may **`POST /v1/jobs`** with **`workspace_upload_required`**, then **`PUT /v1/jobs/{id}/workspace`** with a gzip tarball before Fleet starts **`docker_argv`**. Pick **`workspace_profile`** to match archive size (`large_workspace` vs `generic` limits in `fleet_server/workspace_bundle.py`).
