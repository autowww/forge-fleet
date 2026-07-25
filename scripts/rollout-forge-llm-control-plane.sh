#!/usr/bin/env bash
# Remote/local rollout: clone/pull forge-llm, start gateway (host Ollama), retarget Caddy.
set -euo pipefail

FLEET_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FORGE_LLM_ROOT="${FORGE_LLM_ROOT:-$FLEET_ROOT/deploy/forge-llm-control-plane}"
FORGE_LLM_GIT_URL="${FORGE_LLM_GIT_URL:-https://github.com/autowww/forge-llm.git}"
FORGE_LLM_GIT_BRANCH="${FORGE_LLM_GIT_BRANCH:-main}"
GATEWAY_HOST_PORT="${FORGE_GATEWAY_HOST_PORT:-18080}"
CFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/forge-fleet"
ENV_FILE="$CFG_DIR/forge-fleet.env"

log() { printf 'rollout-forge-llm: %s\n' "$*"; }
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

ensure_forge_llm_checkout() {
  if [[ -f "$FORGE_LLM_ROOT/compose.yaml" ]]; then
    log "using bundled forge-llm control plane at $FORGE_LLM_ROOT"
    return 0
  fi
  if [[ -d "$FORGE_LLM_ROOT" && ! -f "$FORGE_LLM_ROOT/compose.yaml" ]]; then
    log "removing incomplete forge-llm checkout at $FORGE_LLM_ROOT"
    rm -rf "$FORGE_LLM_ROOT"
  fi
  local archive_url="https://github.com/autowww/forge-llm/archive/refs/heads/${FORGE_LLM_GIT_BRANCH}.tar.gz"
  local tmp
  tmp="$(mktemp -d)"
  log "fetching $archive_url"
  if ! curl -fsSL "$archive_url" -o "$tmp/forge-llm.tar.gz"; then
    rm -rf "$tmp"
    die "failed to download forge-llm archive"
  fi
  tar -xzf "$tmp/forge-llm.tar.gz" -C "$tmp"
  rm -rf "$tmp/forge-llm.tar.gz"
  local extracted
  extracted="$(find "$tmp" -maxdepth 1 -type d -name 'forge-llm-*' | head -1)"
  [[ -n "$extracted" && -f "$extracted/compose.yaml" ]] || die "archive missing compose.yaml"
  rm -rf "$FORGE_LLM_ROOT"
  mv "$extracted" "$FORGE_LLM_ROOT"
  rm -rf "$tmp"
  log "extracted forge-llm to $FORGE_LLM_ROOT"
}

ensure_env_file() {
  cd "$FORGE_LLM_ROOT"
  if [[ ! -f .env ]]; then
    cat >.env <<EOF
HOST_BIND_IP=127.0.0.1
GATEWAY_PORT=${GATEWAY_HOST_PORT}
GATEWAY_AUTH_REQUIRED=true
OLLAMA_HOST_URL=http://host.docker.internal:11434
EOF
  fi
  if ! grep -q '^GATEWAY_PORT=' .env; then
    echo "GATEWAY_PORT=$GATEWAY_HOST_PORT" >>.env
  else
    sed -i "s/^GATEWAY_PORT=.*/GATEWAY_PORT=$GATEWAY_HOST_PORT/" .env
  fi
  if ! grep -q '^HOST_BIND_IP=' .env; then
    echo 'HOST_BIND_IP=127.0.0.1' >>.env
  fi
  if ! grep -q '^GATEWAY_AUTH_REQUIRED=' .env; then
    echo 'GATEWAY_AUTH_REQUIRED=true' >>.env
  fi
  if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
    set -a && source "$ENV_FILE" && set +a
  fi
  if [[ -n "${LLM_BEARER_TOKEN:-}" ]] && ! grep -q '^FORGE_API_TOKEN=' .env; then
    echo "FORGE_API_TOKEN=${LLM_BEARER_TOKEN}" >>.env
  fi
  # shellcheck disable=SC1091
  set -a && source .env && set +a
}

deploy_gateway_stack() {
  cd "$FORGE_LLM_ROOT"
  export OLLAMA_HOST_URL="${OLLAMA_HOST_URL:-http://host.docker.internal:11434}"
  log "building forge-gateway"
  compose -f compose.yaml build forge-gateway
  log "starting forge-gateway"
  compose -f compose.yaml up -d forge-gateway
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
  log "registering forge_llm service with Fleet"
  curl -fsS -X POST "http://127.0.0.1:${fleet_port}/v1/container-services" \
    -H "Authorization: Bearer ${fleet_token}" \
    -H "Content-Type: application/json" \
    -d "{\"id\":\"default\",\"type_id\":\"forge_llm\",\"compose_root\":\"${FORGE_LLM_ROOT}\",\"compose_files\":[],\"label\":\"Granite control plane\"}" \
    2>/dev/null || log "Fleet registration skipped (may already exist)"
}

retarget_caddy() {
  local llm_token="${LLM_BEARER_TOKEN:-}"
  local fleet_token="${FLEET_BEARER_TOKEN:-}"
  local site="${CADDY_SITE_ADDRESS:-}"
  if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
    set -a && source "$ENV_FILE" && set +a
    llm_token="${LLM_BEARER_TOKEN:-$llm_token}"
    fleet_token="${FLEET_BEARER_TOKEN:-$fleet_token}"
    site="${CADDY_SITE_ADDRESS:-$site}"
  fi
  [[ -n "$fleet_token" ]] || die "FLEET_BEARER_TOKEN required for Caddy retarget"
  [[ -n "$llm_token" ]] || die "LLM_BEARER_TOKEN required for Caddy retarget"
  export LAYOUT=user
  log "retargeting unified Caddy LLM upstream -> 127.0.0.1:$GATEWAY_HOST_PORT"
  LAYOUT=user \
    OLLAMA_UPSTREAM_HOST=127.0.0.1 \
    OLLAMA_UPSTREAM_PORT="$GATEWAY_HOST_PORT" \
    OLLAMA_UPSTREAM_REINJECT_BEARER=1 \
    FLEET_BEARER_TOKEN="$fleet_token" \
    LLM_BEARER_TOKEN="$llm_token" \
    CADDY_SITE_ADDRESS="$site" \
    bash "$FLEET_ROOT/scripts/install-caddy-fleet-ollama-unified.sh" --non-interactive
}

smoke() {
  cd "$FORGE_LLM_ROOT"
  FORGE_GATEWAY_BASE="http://127.0.0.1:${GATEWAY_HOST_PORT}" \
    FORGE_API_TOKEN="${FORGE_API_TOKEN:-${LLM_BEARER_TOKEN:-}}" \
    LLM_API_KEY="${LLM_API_KEY:-${LLM_BEARER_TOKEN:-}}" \
    ./smoke-control-plane.sh
}


main() {
  command -v git >/dev/null || die "git missing"
  command -v docker >/dev/null || die "docker missing"
  command -v curl >/dev/null || die "curl missing"
  ensure_forge_llm_checkout
  ensure_env_file
  deploy_gateway_stack
  register_fleet_service
  retarget_caddy
  smoke
  log "rollout complete (gateway :$GATEWAY_HOST_PORT, Caddy LLM paths -> gateway)"
}

main "$@"
