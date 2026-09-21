#!/usr/bin/env bash
# Shared primitives for infra LCDL tasks (infra_pg_dump, infra_migrate_*, infra_compose_deploy).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

infra_pg_dump() {
  local dest="${1:-}"
  bash "${ROOT}/scripts/fleet-rollout-backup.sh" "$dest"
}

infra_migrate_plan() {
  local image="${1:-forge-market-app:studio}"
  local db_url="${2:-}"
  docker run --rm -e "FORGE_MARKET_DATABASE_URL=${db_url}" "$image" \
    python -m forge_market.db.migrate plan --json
}

infra_migrate_run() {
  local image="${1:-forge-market-app:studio}"
  local db_url="${2:-}"
  docker run --rm -e "FORGE_MARKET_DATABASE_URL=${db_url}" "$image" \
    python -m forge_market.db.migrate upgrade
}

infra_compose_deploy() {
  local env_name="${1:-prod}"
  FORGE_MARKET_ENV="$env_name" FORGE_MARKET_RUN_SCHEMA_MIGRATE=0 \
    bash "${ROOT}/scripts/rollout-forge-market-studio.sh"
}
