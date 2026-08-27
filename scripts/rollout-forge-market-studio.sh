#!/usr/bin/env bash
# Local Fleet rollout: build/start Market Studio compose stack and register managed service.
# No SSH — operators trigger via POST /v1/admin/forge-market-studio-rollout.
set -euo pipefail

FLEET_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MARKET_STUDIO_ROOT="${FORGE_MARKET_STUDIO_ROOT:-$FLEET_ROOT/deploy/forge-market-studio}"
FORGE_MARKET_ROOT="${FORGE_MARKET_ROOT:-}"
COMPOSE_FILES="${FORGE_MARKET_COMPOSE_FILES:-compose.granite.yaml}"

log() { printf 'rollout-forge-market-studio: %s\n' "$*"; }
die() { log "ERROR: $*"; exit 1; }

resolve_forge_market_root() {
  if [[ -n "${FORGE_MARKET_ROOT}" && -f "${FORGE_MARKET_ROOT}/studio-server/studio_server.py" ]]; then
    printf '%s' "$FORGE_MARKET_ROOT"
    return 0
  fi
  local candidate
  for candidate in \
    "$FLEET_ROOT/../forge-market" \
    "$HOME/forge-market" \
    "$HOME/Code/forge-market"; do
    if [[ -f "$candidate/studio-server/studio_server.py" ]]; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

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
  FORGE_MARKET_ROOT="$(resolve_forge_market_root)" || die "forge-market checkout missing (set FORGE_MARKET_ROOT or clone beside Fleet)"
  export FORGE_MARKET_ROOT
  log "using forge-market root $FORGE_MARKET_ROOT"
}

ensure_env_file() {
  cd "$MARKET_STUDIO_ROOT"
  CFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/forge-fleet"
  ENV_FILE="$CFG_DIR/forge-fleet.env"
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
  _root_override="${FORGE_MARKET_ROOT:-}"
  _dockerfile_override="${FORGE_MARKET_DOCKERFILE:-}"
  # shellcheck disable=SC1091
  set -a && source .env && set +a
  if [[ -n "$_root_override" ]]; then
    FORGE_MARKET_ROOT="$_root_override"
  else
    FORGE_MARKET_ROOT="$(resolve_forge_market_root)" || die "forge-market checkout missing (set FORGE_MARKET_ROOT)"
  fi
  export FORGE_MARKET_ROOT
  if [[ -n "$_dockerfile_override" ]]; then
    export FORGE_MARKET_DOCKERFILE="$_dockerfile_override"
  else
    export FORGE_MARKET_DOCKERFILE="$FLEET_ROOT/deploy/forge-market-studio/Dockerfile.market-app"
  fi
  if grep -q '^FORGE_MARKET_ROOT=' .env 2>/dev/null; then
    sed -i "s|^FORGE_MARKET_ROOT=.*|FORGE_MARKET_ROOT=${FORGE_MARKET_ROOT}|" .env
  else
    echo "FORGE_MARKET_ROOT=${FORGE_MARKET_ROOT}" >>.env
  fi
  if grep -q '^FORGE_MARKET_DOCKERFILE=' .env 2>/dev/null; then
    sed -i "s|^FORGE_MARKET_DOCKERFILE=.*|FORGE_MARKET_DOCKERFILE=${FORGE_MARKET_DOCKERFILE}|" .env
  else
    echo "FORGE_MARKET_DOCKERFILE=${FORGE_MARKET_DOCKERFILE}" >>.env
  fi
}

_sync_git_tree() {
  local root="$1"
  local git_ref="${FORGE_MARKET_GIT_REF:-}"
  if [[ -n "$git_ref" ]]; then
    log "git fetch/checkout ${git_ref} in ${root}"
    git -C "$root" fetch --prune origin "$git_ref" || return 1
    git -C "$root" checkout -B forge-market-rollout "FETCH_HEAD" || return 1
    return 0
  fi
  log "git pull --ff-only in ${root}"
  git -C "$root" pull --ff-only
}

sync_forge_market_checkout() {
  local fallback="${FORGE_MARKET_GIT_FALLBACK_ROOT:-}"
  if [[ -d "${FORGE_MARKET_ROOT}/.git" ]]; then
    if ! _sync_git_tree "${FORGE_MARKET_ROOT}"; then
      log "WARN: forge-market git sync failed — using tree as-is"
    fi
    return 0
  fi
  if [[ -z "$fallback" ]]; then
    for candidate in \
      "/home/administrator/Code/forge-market" \
      "$HOME/Code/forge-market" \
      "$FLEET_ROOT/../forge-market"; do
      if [[ -d "$candidate/.git" ]]; then
        fallback="$candidate"
        break
      fi
    done
  fi
  if [[ -n "$fallback" && -d "$fallback/.git" ]]; then
    log "forge-market root is not git — syncing ${FORGE_MARKET_ROOT} from ${fallback}"
    if ! _sync_git_tree "$fallback"; then
      log "WARN: fallback git sync failed — rsync may be stale"
    fi
    mkdir -p "${FORGE_MARKET_ROOT}"
    rsync -a --delete \
      --exclude .git/ \
      --exclude data/ \
      --exclude .venv/ \
      --exclude studio-ui/node_modules/ \
      --exclude desktop/node_modules/ \
      "${fallback}/" "${FORGE_MARKET_ROOT}/"
    return 0
  fi
  log "forge-market root is not a git checkout — using tree as-is"
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
  local -a build_cmd=(build market-app)
  if [[ "${FORGE_MARKET_DOCKER_BUILD_NO_CACHE:-}" == "1" ]]; then
    build_cmd=(build --no-cache market-app)
  fi
  compose "${files[@]}" "${build_cmd[@]}"
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
  local attempt
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if curl -fsS "$url" 2>/dev/null | grep -q forge-market-studio; then
      return 0
    fi
    sleep 2
  done
  die "health check failed for $url"
}

main() {
  command -v docker >/dev/null || die "docker missing"
  command -v curl >/dev/null || die "curl missing"
  ensure_paths
  ensure_env_file
  sync_forge_market_checkout
  deploy_compose_stack
  register_fleet_service
  smoke
  log "rollout complete (market studio loopback :${FORGE_MARKET_STUDIO_HOST_PORT:-19792})"
  log "optional Granite host edge: forge-market/scripts/granite/install-granite-edge-plane.sh"
  log "optional Granite scheduler: forge-fleet/scripts/install-granite-market-scheduler.sh"
}

main "$@"
