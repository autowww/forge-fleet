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
| Market Studio | ``POST /v1/admin/forge-market-studio-rollout`` | ``scripts/rollout-forge-market-studio.sh`` |

Body ``{"sync": true}`` runs synchronously; default schedules background rollout and returns ``log_path``.

Market Studio rollout **does not use SSH** — it builds from a local ``forge-market`` checkout, starts compose, registers the managed service, and curls ``/health``.

### Use rollout, not start, after a gateway code change

The gateway image bakes ``apps/forge-gateway`` in at build time and ``compose.yaml`` mounts no source volume. ``POST /v1/container-services/<id>/start`` runs ``docker compose up -d`` **without** ``--build``, so it recreates the container from the existing ``forge-gateway:control-plane`` image and silently keeps the old code. After changing gateway source, use ``POST /v1/admin/forge-llm-control-plane-rollout``, which runs ``compose build forge-gateway`` before ``up -d``.

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

## Implementation map

| Module | Role |
|--------|------|
| ``fleet_server/managed_compose_service.py`` | Generic compose ps/start/stop/status |
| ``fleet_server/forge_llm_service.py`` | LLM gateway enrichment on status |
| ``fleet_server/container_layout.py`` | Types catalog + ``etc/services`` persistence |

**Before:** **[Container templates](02-container-templates.md)** · **After:** **[Operate architecture](../operate-301/03-architecture.md)** · **Lookup:** **[HTTP API](../reference/01-http-api-reference.md)**
