# Managed compose services

**Purpose:** register and operate long-lived **Docker Compose** stacks from Fleet using persisted service records under ``$FLEET_DATA_DIR/etc/services/``.

| | |
| --- | --- |
| **Audience** | Granite operators and integrators hosting Forge LLM or Market Studio |
| **Prerequisites** | Fleet running with bearer token; Docker Compose v2 on the host |
| **Success** | ``POST /v1/container-services`` registers a stack; ``…/start`` runs ``docker compose up -d``; status appears on ``GET /v1/container-services`` |

## Container types

Managed compose types inherit the **service** category capability ``api_manage_services: true``.

| ``type_id`` | Compose root (typical) | Notes |
|-------------|------------------------|-------|
| ``forge_llm`` | ``deploy/forge-llm-control-plane`` or external forge-llm checkout | Gateway control plane; legacy ``/v1/services/forge-llm/*`` endpoints |
| ``forge_market_studio`` | ``deploy/forge-market-studio`` | Postgres + ``market-app``; rollout via admin API |

Add types in ``etc/containers/types.json`` or ``GET /v1/container-types``. Only types with ``api_manage_services`` accept ``POST /v1/container-services`` and per-service start/stop.

## Service record shape

Each ``etc/services/<id>.json`` file:

```json
{
  "version": 1,
  "id": "market-studio",
  "type_id": "forge_market_studio",
  "label": "Granite Market Studio",
  "compose_root": "/path/to/deploy/forge-market-studio",
  "compose_files": ["compose.granite.yaml"]
}
```

``compose_files`` lists **overlay** filenames (not ``compose.yaml``). Allowed overlays are validated in ``fleet_server/managed_compose_service.py`` (includes ``compose.granite.yaml``, ``compose.market.yaml``, and forge-llm overlays).

## HTTP API

| Method | Path | Behavior |
|--------|------|----------|
| GET | ``/v1/container-services`` | All service records; compose status when type is API-manageable |
| GET | ``/v1/container-services/{id}`` | One record + status |
| POST | ``/v1/container-services`` | Register or replace (body: ``type_id``, ``compose_root``, ``compose_files``, ``label``) |
| POST | ``/v1/container-services/{id}/start`` | ``docker compose up -d`` |
| POST | ``/v1/container-services/{id}/stop`` | ``docker compose down`` |
| DELETE | ``/v1/container-services/{id}`` | Remove record (**409** if stack still running) |

**Legacy forge_llm-only:**

| Method | Path |
|--------|------|
| GET | ``/v1/services/forge-llm`` |
| POST | ``/v1/services/forge-llm/start`` |
| POST | ``/v1/services/forge-llm/stop`` |

## Rollout helpers

| Stack | Admin route | Host script |
|-------|-------------|-------------|
| Forge LLM gateway | ``POST /v1/admin/forge-llm-control-plane-rollout`` | ``scripts/rollout-forge-llm-control-plane.sh`` |
| Market Studio | ``POST /v1/admin/forge-market-studio-rollout`` (409 when same env busy) | ``scripts/rollout-forge-market-studio.sh`` |
| Pattern cell rollups backfill | ``POST /v1/admin/forge-market-pattern-rollups-backfill`` (409 when same env busy) | ``scripts/backfill-forge-market-pattern-rollups.sh`` |

Infra flows via ``POST /v1/flows/submit`` (e.g. ``market-studio-rollout``) use the same per-``service_id`` slot; parallel rollouts across **different** envs (prod vs dev) are allowed.

Body ``{"sync": true}`` runs synchronously; default schedules background rollout and returns ``log_path``.

Market Studio rollout **does not use SSH** — it builds from a local ``forge-market`` checkout, starts compose, registers the managed service, and curls ``/health``.

### Use rollout, not start, after a gateway code change

The gateway image bakes ``apps/forge-gateway`` in at build time and ``compose.yaml`` mounts no source volume. ``POST /v1/container-services/<id>/start`` runs ``docker compose up -d`` **without** ``--build``, so it recreates the container from the existing ``forge-gateway:control-plane`` image and silently keeps the old code. After changing gateway source, use ``POST /v1/admin/forge-llm-control-plane-rollout``, which runs ``compose build forge-gateway`` before ``up -d``.

### Runner config and host Ollama apply

Bundled tree: ``deploy/forge-llm-control-plane/`` (gateway source, ``configs/runner.granite.yaml``, ``scripts/apply-runner-host.sh``). Sync from standalone **forge-llm** when gateway or runner YAML changes.

Rollout calls ``apply-runner-host.sh`` before starting the gateway:

| ``FORGE_LLM_RUNNER_APPLY`` | Effect |
|---------------------------|--------|
| ``observe`` (default) | Log ``ollama.service`` + ``ollama list``; log would-be drop-in / pulls |
| ``apply`` | Write systemd user drop-in for keys in ``runtime:``; ``ollama pull`` missing catalog models |

Gateway mounts ``configs/runner.granite.yaml`` as ``/config/runner.yaml`` and exposes ``GET /v1/llm/runner`` and ``GET /v1/llm/catalog``.

### Runner YAML changes force a gateway recreate

That mount is a **single-file** bind. ``git pull`` / ``update-user.sh`` replace the file with a new inode, which a running container never sees, and ``docker compose up -d`` does not recreate a container because a mounted file's bytes changed. Before 0.3.187 a promoted artifact pin could ship, the rollout log could say ``rollout complete``, and ``GET /v1/llm/catalog`` would still report the old ``config_hash`` and ``deployment_authorized: false`` (observed on Granite, P2B 2026-11-04; recovered by ``POST /v1/container-services/default/stop`` then ``/start``).

``deploy_gateway_stack`` now hashes the host ``configs/runner.granite.yaml`` and the container's ``/config/runner.yaml`` (``docker exec … cat``) and passes ``--force-recreate`` only when they differ; the log line says which branch was taken. Covered by ``tests/test_forge_llm_rollout_recreate.py``. Catalog JSON under ``configs/catalog/`` is a directory mount and does not have this problem. Host Ollama binds loopback only, so the gateway container reaches it through the host **11436 → 11434** forwarder (``OLLAMA_HOST_URL=http://host.docker.internal:11436``, the rollout migrates a stale ``:11434`` ``.env``); Forge apps use Caddy → gateway **:18080**. Open WebUI's chat models come from the gateway's OpenAI connection, not direct Ollama.

## LLM request queue (bounce vs hold)

``control_plane/queue_manager.py`` serialises inference behind one concurrent slot. ``DEFAULT_WAIT_BY_MODE`` in ``control_plane/modes.py`` decides how a caller waits when that slot is taken:

| Wait mode | Modes | Behaviour when the slot is busy |
|-----------|-------|--------------------------------|
| ``bounce`` | ``interactive``, ``struct_json``, ``reason_short``, ``embed`` | Immediate ``503`` with ``reason: busy`` and ``Retry-After``; the caller does **not** join the queue |
| ``hold`` | ``task_code``, ``long_ctx``, ``codegen_loop`` | Joins the queue and waits up to ``FORGE_LLM_HOLD_TIMEOUT_SEC`` (default 300s) |

Queue depth is capped by ``FORGE_LLM_MAX_QUEUE_DEPTH`` (default **64**). Only ``hold`` callers occupy a slot — a bounced caller stops waiting the moment it receives its ``503``, so enqueuing one would leak its slot forever.

### Diagnosing a wedged queue

A saturated queue and a wedged queue look identical from the client (``503`` / ``queue_busy`` / ``code: queue_full``). Tell them apart by whether ``queue_position`` **moves**:

- **Real load** — ``queue_position`` fluctuates between calls.
- **Wedged** — ``queue_position`` is pinned at exactly ``FORGE_LLM_MAX_QUEUE_DEPTH`` across repeated calls and never drains, because every slot is held by a ticket whose waiter is gone.

Confirm against the gateway rather than the client: ``GET /v1/active`` reports ``queue_depth``, and ``0`` there while clients still see ``queue_full`` means the queue is fine and the problem is elsewhere. Recover with ``POST /v1/admin/forge-llm-control-plane-rollout`` — queue state is in-process, so a restart clears it.

Two accounting rules keep the queue from wedging, both covered by ``apps/forge-gateway/tests/test_queue_manager.py``:

1. A ``bounce`` caller is never enqueued.
2. When ``release()`` hands the active slot to a ticket whose waiter has already timed out, the timed-out caller returns that slot instead of stranding it.

Tickets older than twice the hold timeout are reaped on the next ``acquire``, so a missed path degrades to a self-healing delay rather than an outage that needs a restart.

Future migration jobs may use template ``build_market_image`` (see ``forge-migrator`` recipe) to build on Granite without manual SSH.

## Example — register Market Studio manually

```bash
export FLEET=http://127.0.0.1:18766
export TOKEN=…

curl -fsS -X POST "$FLEET/v1/container-services" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "market-studio",
    "type_id": "forge_market_studio",
    "compose_root": "/home/you/forge-fleet/deploy/forge-market-studio",
    "compose_files": ["compose.granite.yaml"],
    "label": "Market Studio"
  }'

curl -fsS -X POST "$FLEET/v1/container-services/market-studio/start" \
  -H "Authorization: Bearer $TOKEN"
```

## Forge 2B PoC stack (`forge_2b_poc`)

`deploy/forge-2b-poc/` runs two containers from one image: **forge-dcs** (ingest + STRICT compile, store volume `forge_2b_dcs_store`) and **forge-2b** (OpenAI-compatible shim on `:9085`, graph executor that makes one atomic `qwen3.5:2b-q4_K_M` decision per source window through the forge-llm gateway on `host.docker.internal:18080`). The shim joins the Open WebUI compose network so Open WebUI reaches it as `http://forge-2b:9085/v1`.

1. On the laptop: `scripts/sync-forge-2b-poc.sh` copies `forge_dcs` and `forge_2b` sources into `deploy/forge-2b-poc/vendor/` (git is the only code carrier; `vendor/SOURCES.txt` records both commits). Ship with `update-fleet.sh`.
2. On the host: create `~/.config/forge-2b-poc/forge-2b.env` from `forge-2b.env.example` (mode 600), then `scripts/rollout-forge-2b-poc.sh` — builds the image, `up -d --force-recreate`, waits for both health checks.
3. Register once: `POST /v1/container-services` with `type_id: forge_2b_poc`, `compose_root: <fleet>/deploy/forge-2b-poc`; start/stop then work through the Fleet API (they do not rebuild — rerun the rollout script after code changes).
4. Open WebUI: append `http://forge-2b:9085/v1` + the shim's `FORGE_2B_API_KEY` to `openai.api_base_urls` / `openai.api_keys`, add `openai.api_configs[<index>] = {"enable": true, "prefix_id": "forge-2b-poc", "provider": "openai"}`, and raise `AIOHTTP_CLIENT_TIMEOUT` (graph runs over a full 10-K take minutes). The model appears as `forge-2b-poc.forge-2b`.

## Implementation map

| Module | Role |
|--------|------|
| ``fleet_server/managed_compose_service.py`` | Generic compose ps/start/stop/status |
| ``fleet_server/forge_llm_service.py`` | LLM gateway enrichment on status |
| ``fleet_server/container_layout.py`` | Types catalog + ``etc/services`` persistence |

**Before:** **[Container templates](02-container-templates.md)** · **After:** **[Operate architecture](../operate-301/03-architecture.md)** · **Lookup:** **[HTTP API](../reference/01-http-api-reference.md)**
