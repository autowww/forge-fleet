#!/usr/bin/env bash
# Local Fleet rollout: build/start Market Studio compose stack and register managed service.
# No SSH — operators trigger via POST /v1/admin/forge-market-studio-rollout.
set -euo pipefail

FLEET_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MARKET_STUDIO_ROOT="${FORGE_MARKET_STUDIO_ROOT:-$FLEET_ROOT/deploy/forge-market-studio}"
FORGE_MARKET_ROOT="${FORGE_MARKET_ROOT:-$FLEET_ROOT/../forge-market}"
CFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/forge-fleet"
ENV_FILE="$CFG_DIR/forge-fleet.env"
COMPOSE_FILES="${FORGE_MARKET_COMPOSE_FILES:-compose.granite.yaml}"

log() { printf 'rollout-forge-market-studio: %s\n' "$*"; }
die() { log "ERROR: $*"; exit 1; }

compose() {
  if docker compose version &>/dev/null; then
    docker compose "$@"
  elif command -v docker-compose &>/dev/null; then
    docker-compose "$@"
  else
    log "ERROR: docker compose not available"
    return 127
  fi
}

ensure_paths() {
  [[ -f "$MARKET_STUDIO_ROOT/compose.yaml" ]] || die "missing $MARKET_STUDIO_ROOT/compose.yaml"
  [[ -d "$FORGE_MARKET_ROOT" ]] || die "forge-market checkout missing at $FORGE_MARKET_ROOT"
  [[ -f "$FORGE_MARKET_ROOT/studio-server/studio_server.py" ]] \
    || die "forge-market studio server missing under $FORGE_MARKET_ROOT"
}

ensure_env_file() {
  cd "$MARKET_STUDIO_ROOT"
  if [[ ! -f .env ]]; then
    if [[ -f .env.example ]]; then
      cp .env.example .env
      log "created .env from .env.example — review secrets before production"
    else
      cat >.env <<EOF
FORGE_MARKET_ROOT=${FORGE_MARKET_ROOT}
POSTGRES_USER=forge_market
POSTGRES_PASSWORD=forge_market_dev
POSTGRES_DB=forge_market
FORGE_MARKET_DATABASE_URL=postgresql://forge_market:forge_market_dev@postgres:5432/forge_market
FORGE_MARKET_STUDIO_HOST_PORT=19792
FORGE_MARKET_POSTGRES_HOST_PORT=15432
EOF
    fi
  fi
  if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    set -a && source "$ENV_FILE" && set +a
  fi
  # shellcheck disable=SC1091
  set -a && source .env && set +a
  export FORGE_MARKET_ROOT
  export FORGE_MARKET_DOCKERFILE="${FORGE_MARKET_DOCKERFILE:-$FLEET_ROOT/deploy/forge-market-studio/Dockerfile.market-app}"
}

deploy_compose_stack() {
  cd "$MARKET_STUDIO_ROOT"
  local -a files=(-f compose.yaml)
  if [[ -n "$COMPOSE_FILES" ]]; then
    IFS=',' read -ra overlays <<<"$COMPOSE_FILES"
    for ov in "${overlays[@]}"; do
      ov="${ov#"${ov%%[![:space:]]*}"}"
      ov="${ov%"${ov##*[![:space:]]}"}"
      [[ -n "$ov" ]] || continue
      [[ -f "$ov" ]] || die "compose overlay missing: $ov"
      files+=(-f "$ov")
    done
  fi
  log "building market-app image (context $FORGE_MARKET_ROOT)"
  compose "${files[@]}" build market-app
  log "starting forge-market-studio stack"
  compose "${files[@]}" up -d
}

register_fleet_service() {
  local fleet_port="${FLEET_LOCAL_PORT:-18766}"
  local fleet_token="${FLEET_BEARER_TOKEN:-}"
  if [[ -z "$fleet_token" && -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    set -a && source "$ENV_FILE" && set +a
    fleet_token="${FLEET_BEARER_TOKEN:-}"
  fi
  if [[ -z "$fleet_token" ]]; then
    log "skip Fleet service registration (no FLEET_BEARER_TOKEN)"
    return 0
  fi
  local cf_json
  if [[ -n "$COMPOSE_FILES" ]]; then
    cf_json="[\"$(echo "$COMPOSE_FILES" | cut -d, -f1 | xargs)\"]"
  else
    cf_json="[]"
  fi
  log "registering forge_market_studio service with Fleet"
  curl -fsS -X POST "http://127.0.0.1:${fleet_port}/v1/container-services" \
    -H "Authorization: Bearer ${fleet_token}" \
    -H "Content-Type: application/json" \
    -d "{\"id\":\"market-studio\",\"type_id\":\"forge_market_studio\",\"compose_root\":\"${MARKET_STUDIO_ROOT}\",\"compose_files\":${cf_json},\"label\":\"Granite Market Studio\"}" \
    2>/dev/null || log "Fleet registration skipped (may already exist)"
}

smoke() {
  local port="${FORGE_MARKET_STUDIO_HOST_PORT:-19792}"
  local url="http://127.0.0.1:${port}/health"
  log "smoke: GET $url"
  curl -fsS "$url" | grep -q forge-market-studio || die "health check failed for $url"
}

main() {
  command -v docker >/dev/null || die "docker missing"
  command -v curl >/dev/null || die "curl missing"
  ensure_paths
  ensure_env_file
  deploy_compose_stack
  register_fleet_service
  smoke
  log "rollout complete (market studio loopback :${FORGE_MARKET_STUDIO_HOST_PORT:-19792})"
}

main "$@"
