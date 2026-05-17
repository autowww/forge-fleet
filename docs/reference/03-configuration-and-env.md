# Configuration and environment variables

Fleet reads **environment variables** at process start. Production installs often set them in **`forge-fleet.env`** (see **`systemd/environment.example`** in the repo).

Values are **case-sensitive**. Empty/unset usually means “use default” where a default exists.

## Core server

| Variable | Purpose |
|----------|---------|
| **`FLEET_DATA_DIR`** | Directory for **`fleet.sqlite`** and **`etc/`** layout (default `.fleet-data` or CLI **`--data-dir`**). |
| **`FLEET_BEARER_TOKEN`** | Shared secret for **`Authorization: Bearer`** on **`/v1/*`** when policy requires it. |
| **`FLEET_ENFORCE_BEARER`** | If **`1`/`true`/`yes`**, require bearer even on loopback when token is set. |

## Git / version metadata

| Variable | Purpose |
|----------|---------|
| **`FLEET_GIT_ROOT`** | Checkout used for self-update and SHA resolution. |
| **`FLEET_GIT_SHA`** / **`SOURCE_GIT_COMMIT`** | Override recorded git SHA for **`/v1/version`**. |
| **`FLEET_SELF_UPDATE_INSTALL_PROFILE`** | **`system`** suppresses user-install self-update button behavior. |
| **`FLEET_SELF_UPDATE_POST_GIT_COMMAND`** | Custom command after **`git pull`** for self-update. |

## Integrations (admin snapshot, compose)

| Variable | Purpose |
|----------|---------|
| **`FLEET_FORGE_CONSOLE_URL`** | Optional Forge Console URL in snapshot **`meta.integrations`**. |
| **`FLEET_FORGE_LLM_ROOT`** | Auto-migration hint for Forge LLM compose trees; snapshot integration. |
| **`FLEET_FORGE_LLM_COMPOSE_FILES`** | Optional override for compose file list when migrating services. |

## Telemetry and cooldown

| Variable | Purpose |
|----------|---------|
| **`FLEET_TELEMETRY_INTERVAL_S`** | Minimum seconds between throttled samples (default **60**, floor **5**). |
| **`FLEET_TELEMETRY_RETENTION_DAYS`** | Prune old telemetry + cooldown rows (**0** may mean no prune — see **`store.py`**). |
| **`FLEET_COOLDOWN_EVENT_MAX_S`** | Max recorded **`duration_s`** per cooldown event (default **86400**). |

## Workspace and template uploads

| Variable | Purpose |
|----------|---------|
| **`FLEET_WORKSPACE_UPLOAD_MAX_BYTES`** | Max gzip tarball size for **`PUT .../workspace`**. |
| **`FLEET_TEMPLATE_PACKAGE_UPLOAD_MAX_BYTES`** | Max uploaded template package bytes. |
| **`FLEET_TEMPLATE_PACKAGE_MAX_UNCOMPRESSED_BYTES`** | Extracted size guard for template packages. |
| **`FLEET_TEMPLATE_PACKAGE_MAX_FILES`** | File count guard. |
| **`FLEET_TEMPLATE_PACKAGE_MAX_PATH_DEPTH`** | Path depth guard. |
| **`FLEET_DOCKER_BUILDKIT`** | Pass-through for **`docker build`** BuildKit preference. |

## Runner / Docker

| Variable | Purpose |
|----------|---------|
| **`FLEET_DOCKER_BIN`** | Explicit **`docker`** binary path. |
| **`FLEET_INJECT_HOST_METRICS_ENV_IN_DOCKER`** | If set, inject host metrics URL/token into job env (see [HTTP API reference](01-http-api-reference.md)). |
| **`FLEET_HOST_METRICS_BASE_URL`** | Base URL reachable **from inside** containers for health polling. |
| **`FLEET_LENSES_WORKSPACE_ROOT`** | Doc/test fleet integration path (see **`test_fleet.py`** / README). |
| **`FLEET_LENSES_REPO_ROOT`** | Optional Lenses repo hint (**`containers.py`**). |
| **`FLEET_EMPTY_CONTAINER_IMAGE`** / **`FLEET_TEST_CONTAINER_IMAGE`** | Image defaults for internal helpers. |

## Thermal / advisory (LLM)

| Variable | Purpose |
|----------|---------|
| **`FLEET_THERMAL_CPU_DEFAULT`** | Policy default tier behavior (**`thermal_llm_policy.py`**). |
| **`FLEET_ARM_SOC_TJMAX_C`** | SoC thermal ceiling hint on ARM. |

## See also

- **[SECURITY.md](../operate-301/01-security.md)** — sensitivity and threat notes  
- **[README.md](../../README.md)** — install-specific **`forge-fleet.env`** examples
