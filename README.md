# forge-fleet

Small **HTTP + bearer** orchestrator for **Docker argv** workloads (MVP: same host as Lenses so bind-mount paths match). **Forge Lenses** can set `LENSES_FLEET_URL` + `LENSES_FLEET_TOKEN` (or Studio **Settings → Fleet**) so Docs Health `session_step` runs containers via Fleet instead of in-process `docker` CLI.

## API (v1)

| Method | Path | Notes |
|--------|------|--------|
| GET | `/v1/health` | `{ "ok": true }` |
| POST | `/v1/jobs` | Body: `{ "kind": "docker_argv", "argv": ["docker", "run", ...], "session_id": "..." }` → `{ "id": "..." }` |
| GET | `/v1/jobs/{id}` | Status: `queued`, `running`, `completed`, `failed`, `cancelled` + `stdout` / `stderr` / `exit_code` |
| POST | `/v1/jobs/{id}/cancel` | Best-effort kill |
| GET | `/v1/admin/snapshot` | **Read-only** JSON: host load/memory, **`host.gpu`** (NVIDIA via `nvidia-smi` when available), `jobs_by_status`, `jobs_recent` (argv preview, no full logs), `active_workers` (PID + argv preview for running subprocesses) |
| GET | `/admin/` | Browser admin UI (same bearer token as API when auth is enabled) |
| GET | `/admin/theme.css` | Optional **kitchensink** stylesheet when the `kitchensink/` submodule is checked out |

Auth:

- **`FLEET_BEARER_TOKEN`** set and listen **`--host`** is **not** loopback-only (`127.0.0.1`, `::1`, `localhost`): every `/v1/...` request must send `Authorization: Bearer <token>`.
- **Loopback-only bind** (`--host 127.0.0.1` / `::1` / `localhost`) **with a token configured**: bearer is **not** required (same machine only; Lenses may still send a token). Override with **`FLEET_ENFORCE_BEARER=1`** if you need the token checked even on loopback.
- **No token** in env: requests are accepted on any bind address (avoid in production).

## Submodules (blueprints + kitchensink)

This repo vendors the same read-only **blueprints** and **kitchensink** submodules as other Forge sites (`forgesdlc`, `forge-lenses`, …). After clone:

```bash
git submodule update --init --recursive
```

Edits belong in the standalone `blueprints` / `forgesdlc-kitchensink` repos, not inside submodule paths here.

## Run locally

```bash
cd forge-fleet
export FLEET_BEARER_TOKEN='dev-token'   # optional
python3 -m fleet_server --host 127.0.0.1 --port 18765
```

Point Lenses at `http://127.0.0.1:18765` and set the same token in Studio Fleet settings or `LENSES_FLEET_TOKEN`.

## Docker Compose

```bash
docker compose up --build
```

Default compose maps port **18765**; set `FLEET_BEARER_TOKEN` in `.env` for non-dev use.

## Roadmap (deferred)

- **P2 — Remote agent:** worker registers from another host; jobs survive laptop sleep; Lenses shows completed jobs for port-back (see `forge-lenses/docs/maintainer/docs-health-port-back.md`).
- **P3 — Cloud adapters:** same `JobSpec` translated to Kubernetes Job, Nomad batch, or Temporal — avoid reinventing durable execution at scale.

## Limitations (MVP)

- Fleet runs `docker` on **the same machine** that built the argv (paths are host paths).
- Stdout is capped in DB for safety; last JSON line must remain parseable for Lenses `step_cli` contract.
