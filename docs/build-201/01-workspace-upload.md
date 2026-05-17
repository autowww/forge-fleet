# Forge Fleet — job workspace upload (`PUT /v1/jobs/{id}/workspace`)

Optional **gzip-compressed tarball** staging for `docker_argv` jobs so workers do not rely on host bind-mounts of consumer repos.

```blueprint-diagram-ascii
key: sequence
alt: Workspace upload sequence between client and Fleet
caption: Create job with workspace_upload_required, upload tarball, then runner starts.
Client -> Fleet POST job pending_upload
Client -> Fleet PUT workspace bytes
Fleet -> Fleet extract validate ready
Fleet -> Docker run with volume
```

## Flow

1. **`POST /v1/jobs`** with JSON body including `"meta": { "workspace_upload_required": true, … }`.  
   Fleet creates the job with `meta.workspace_state` set to `pending_upload` and **does not** call the runner until the workspace exists.

2. **`PUT /v1/jobs/{job_id}/workspace`** with the raw bytes of a **`.tar.gz`** file (`Content-Type: application/gzip` recommended).  
   Requires the same **bearer auth** as other Fleet admin APIs (unless loopback auth skip applies). Optional header **`X-Workspace-Archive-Sha256`**: hex digest of the body; when set it must match or Fleet returns **`400`**.

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
| `workspace_manifest_files_verified` | After extract, count of manifest entries whose size and SHA-256 matched on disk. |
| `workspace_manifest_schema_version` | Present when a manifest was verified (currently `1`). |

## Workspace worker bridge (no bearer)

Some `docker_argv` jobs run an inner worker that must read **argv + cwd** from Fleet without the admin bearer. For those jobs, `POST /v1/jobs` stores:

| Meta key | Meaning |
|----------|---------|
| `workspace_worker_token` | Per-job secret; never returned in full from `GET /v1/jobs/{id}` (redacted). |
| `workspace_worker_bundle` | JSON object: `{ "argv": ["…"], "cwd": "/workspace" }`. |

HTTP (worker uses `X-Workspace-Worker-Token` matching `workspace_worker_token`):

1. `GET /v1/jobs/{id}/workspace-worker-bundle` — JSON `{ "ok", "argv", "cwd" }`.
2. `POST /v1/jobs/{id}/workspace-worker-progress` — JSON body merged into `worker_progress`.
3. `POST /v1/jobs/{id}/workspace-worker-complete` — JSON body stored as `worker_result`.

## Manifest and upload digest

Optional **`X-Workspace-Archive-Sha256`** on **`PUT …/workspace`**: hex SHA-256 of the raw request body. If present and it does not match the body, Fleet returns **`400`** with `archive_sha256_mismatch`.

If the extracted tree contains **`.forge_workspace_manifest.json`** (schema version `1`, `files[]` with `path`, `size`, `sha256`), Fleet **re-hashes** each listed file under `extracted/` and rejects the upload on mismatch (`manifest_verification_failed:…`).

When **`meta.workspace_manifest_required`** is true, Fleet requires that manifest file to exist after extract.

**`200` response** from `PUT …/workspace` includes `workspace_sha256`, `workspace_upload_bytes`, `workspace_uncompressed_bytes`, `manifest_files_verified`, and `manifest_schema_version` when applicable.

## Operator limits

- **`FLEET_WORKSPACE_UPLOAD_MAX_BYTES`** — max HTTP body for `PUT` (default 256 MiB).
- Startup GC (in `fleet_server.main`) removes stale dirs under `job-workspaces/` (orphan `job_id` or queued upload pending too long, default max age **7 days**).

## Security

Upload is **authenticated** like `POST /v1/jobs`. Tar extraction rejects absolute paths, `..`, and symlinks/hardlinks in the archive. Sandboxing untrusted code still requires tight **Docker** / **gVisor** / VM policy on the Fleet host; see project security guidance.

## Consumers

Any authenticated client may **`POST /v1/jobs`** with **`workspace_upload_required`**, then **`PUT /v1/jobs/{id}/workspace`** with a gzip tarball before Fleet starts **`docker_argv`**. Pick **`workspace_profile`** to match archive size (`large_workspace` vs `generic` limits in `fleet_server/workspace_bundle.py`).
