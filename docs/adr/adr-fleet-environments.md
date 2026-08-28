# ADR: Fleet environment provisioning

**Status:** Accepted  
**Date:** 2026-08-28

## Context

Forge Fleet already manages compose stacks (container services, app gateways, Market Studio rollout) but has no first-class **environment** model. Operators hand-maintain `deploy/forge-market-studio` and `deploy/forge-market-studio-dev` with duplicated `.env` files and separate rollout scripts.

Lenses Studio needs a generic wizard to create DEV/PROD (and other) environments from templates. Market Studio needs a persisted gateway URL selector so the workstation thin client can target the right remote stack.

## Decision

Introduce a **generic environment subsystem** in Fleet:

1. **Environment records** under `$FLEET_DATA_DIR/etc/environments/{app}--{env}.json`.
2. **Environment templates** (`env_templates.py`) describing how to render `.env` and compose identity for an app.
3. **Provisioning API** (`POST /v1/environments`) with async progress log.
4. **Seed modes:** `clean` (empty volumes + migrate) and `replicate` (stop source, cold-copy volumes, migrate target).
5. **Lifecycle:** start, stop, delete (with optional volume purge).
6. **Adopt path** for existing hand-made stacks without modifying them.

Provisioning runs **on the Fleet host** via the existing admin API (no SSH).

## Environment record

See `docs/schemas/environment.schema.json`. Key fields:

| Field | Purpose |
|-------|---------|
| `id` | `{app_id}--{env_id}` |
| `app_id` | Logical app (e.g. `forge-market-studio`) |
| `env_id` | Short slug (`prod`, `dev`, `staging`) |
| `template_id` | Template used to render `.env` |
| `compose_root` | Absolute path to compose directory |
| `container_service_id` | Fleet managed service id |
| `gateway_slug` | App gateway service id |
| `ports` | Loopback host ports (`app`, `postgres`, …) |
| `volumes` | Docker volume names |
| `state` | Provisioning state machine value |
| `adopted` | `true` when materialised from an existing stack |

## Template descriptor

Templates capture:

- `source_compose_root` — directory to copy when provisioning
- `compose_overlay` — overlay filename (e.g. `compose.granite.yaml`)
- `app_service_name` — primary service for health/migrate
- `env_keys` — list of `.env` keys with rewrite rules (`literal`, `port`, `suffix`, `compose_project`, …)
- `port_ranges` — suggested loopback ranges for auto-allocation
- `volume_map` — volume env keys → suffix pattern
- `migrate_command` — compose run command for schema migrate
- `gateway` — slug pattern, upstream port key, bearer env key

## Provisioning state machine

```
pending → provisioning → seeding → migrating → registering → ready
                                                      ↘ failed
```

- **provisioning:** allocate ports, copy compose root, render `.env`, create volumes
- **seeding:** `clean` = skip; `replicate` = cold-copy volumes from source
- **migrating:** postgres up, run migrate command
- **registering:** compose up, container-service + app-gateway registration, health smoke

Failed provisions run a cleanup path (remove generated compose dir, volumes, gateway) when `provisioned_at` is set and state is `failed`.

## Volume replication

When `seed: replicate`, the source stack is stopped (`compose down` or `stop` services). Each mapped volume is copied with a throwaway helper container:

```bash
docker run --rm -v src:/from:ro -v dst:/to alpine sh -c 'cp -a /from/. /to/'
```

Source is restarted when `restart_source: true` (default). A per-app provisioning lock prevents concurrent replicate/provision operations.

## Port allocation

Loopback-only ports matching `validate_loopback_upstream` in `app_gateway.py`. Allocator binds `127.0.0.1:port` to confirm availability before writing `.env`.

## API surface

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/environments` | List (optional `?app=`) |
| GET | `/v1/environments/{id}` | Single record + deployment status |
| GET | `/v1/environments/templates` | List templates |
| POST | `/v1/environments` | Provision (`seed: clean\|replicate`) |
| POST | `/v1/environments/{id}/replicate` | Re-seed from another environment |
| POST | `/v1/environments/{id}/start` | `compose up -d` |
| POST | `/v1/environments/{id}/stop` | `compose stop` |
| DELETE | `/v1/environments/{id}` | Deregister gateway; optional `?purge_volumes=1` |
| GET | `/v1/environments/provision-log` | Async progress log |

## Open questions ledger

| # | Question | Resolution |
|---|----------|------------|
| 1 | Provisioning transport | Fleet host admin API only |
| 2 | Volume replication method | Alpine helper container cold-copy |
| 3 | Port scope | Loopback only |
| 4 | PROD replicate during live test | Defer if PROD unreachable; use clean seed |
| 5 | Bearer hydration on gateway PUT | Read from target `.env` via `app_bearer_env` |

## Consequences

- Lenses proxies `/api/environments*` behind `LENSES_EXPERIMENTAL_ENVIRONMENTS`.
- Market Studio persists `gateway_url` in data-plane pref; launchers stop clobbering it.
- Existing `market-studio` / `market-studio-dev` stacks are adopted, not duplicated.
