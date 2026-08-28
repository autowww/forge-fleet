#!/usr/bin/env bash
# Local Fleet rollout: build/start Market Studio compose stack and register managed service.
# No SSH — operators trigger via POST /v1/admin/forge-market-studio-rollout.
set -euo pipefail

FLEET_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FORGE_MARKET_ENV="${FORGE_MARKET_ENV:-prod}"
FORGE_MARKET_ROOT="${FORGE_MARKET_ROOT:-}"
COMPOSE_FILES="${FORGE_MARKET_COMPOSE_FILES:-compose.granite.yaml}"
FORGE_MARKET_SKIP_BUILD="${FORGE_MARKET_SKIP_BUILD:-0}"

log() { printf 'rollout-forge-market-studio: %s\n' "$*"; }
die() { log "ERROR: $*"; exit 1; }

case "$FORGE_MARKET_ENV" in
  dev)
    MARKET_STUDIO_ROOT="${FORGE_MARKET_STUDIO_ROOT:-$FLEET_ROOT/deploy/forge-market-studio-dev}"
    ;;
  prod)
    MARKET_STUDIO_ROOT="${FORGE_MARKET_STUDIO_ROOT:-$FLEET_ROOT/deploy/forge-market-studio}"
    ;;
  *)
    die "FORGE_MARKET_ENV must be dev or prod (got: ${FORGE_MARKET_ENV})"
    ;;
esac

resolve_forge_market_root() {
  if [[ -n "${FORGE_MARKET_ROOT}" && -f "${FORGE_MARKET_ROOT}/studio-server/studio_server.py" ]]; then
    printf '%s' "$FORGE_MARKET_ROOT"
    return 0
  fi
  local candidate
  for candidate in \
    "/home/administrator/forge-market" \
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

_persist_compose_env_key() {
  local key="$1"
  local val="${2:-}"
  [[ -n "$val" ]] || return 0
  if grep -q "^${key}=" .env 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${val}|" .env
  else
    echo "${key}=${val}" >>.env
  fi
  export "${key}=${val}"
}

_default_pgdata_volume() {
  if [[ "$FORGE_MARKET_ENV" == "dev" ]]; then
    printf '%s' "forge_market_studio_dev_pgdata"
  else
    printf '%s' "forge_market_studio_pgdata"
  fi
}

_default_studio_host_port() {
  if [[ "$FORGE_MARKET_ENV" == "dev" ]]; then
    printf '%s' "19793"
  else
    printf '%s' "19792"
  fi
}

_default_postgres_host_port() {
  if [[ "$FORGE_MARKET_ENV" == "dev" ]]; then
    printf '%s' "15433"
  else
    printf '%s' "15432"
  fi
}

_resolve_git_sha12() {
  local sha=""
  if [[ -n "${FORGE_MARKET_GIT_SHA:-}" ]]; then
    sha="${FORGE_MARKET_GIT_SHA}"
  elif [[ -d "${FORGE_MARKET_ROOT}/.git" ]]; then
    sha="$(git -C "${FORGE_MARKET_ROOT}" rev-parse --short=12 HEAD 2>/dev/null || true)"
  fi
  printf '%.12s' "$sha"
}

ensure_env_file() {
  cd "$MARKET_STUDIO_ROOT"
  CFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/forge-fleet"
  ENV_FILE="$CFG_DIR/forge-fleet.env"
  GRANITE_MARKET_ENV="$CFG_DIR/forge-market-granite.env"
  local pgdata_vol
  pgdata_vol="$(_default_pgdata_volume)"
  local studio_port postgres_port
  studio_port="$(_default_studio_host_port)"
  postgres_port="$(_default_postgres_host_port)"
  if [[ ! -f .env ]]; then
    if docker volume inspect "$pgdata_vol" &>/dev/null; then
      log "existing pgdata volume ($pgdata_vol) — seeding .env with stable compose defaults"
      if [[ "$FORGE_MARKET_ENV" == "dev" ]]; then
        cat >.env <<EOF
FORGE_MARKET_COMPOSE_PROJECT=forge-market-studio-dev
FORGE_MARKET_PG_CONTAINER=forge-market-postgres-dev
FORGE_MARKET_APP_CONTAINER=forge-market-app-dev
FORGE_MARKET_APP_IMAGE=forge-market-app:studio
FORGE_MARKET_PGDATA_VOLUME=forge_market_studio_dev_pgdata
FORGE_MARKET_APPDATA_VOLUME=forge_market_studio_dev_data
FORGE_MARKET_ROOT=${FORGE_MARKET_ROOT}
POSTGRES_USER=forge_market
POSTGRES_PASSWORD=forge_market_dev
POSTGRES_DB=forge_market
FORGE_MARKET_DATABASE_URL=postgresql://forge_market:forge_market_dev@postgres:5432/forge_market
FORGE_MARKET_STUDIO_HOST_PORT=${studio_port}
FORGE_MARKET_POSTGRES_HOST_PORT=${postgres_port}
FORGE_MARKET_API_ONLY=1
INCLUDE_STUDIO_UI=0
EOF
      else
        cat >.env <<EOF
FORGE_MARKET_ROOT=${FORGE_MARKET_ROOT}
POSTGRES_USER=forge_market
POSTGRES_PASSWORD=forge_market_dev
POSTGRES_DB=forge_market
FORGE_MARKET_DATABASE_URL=postgresql://forge_market:forge_market_dev@postgres:5432/forge_market
FORGE_MARKET_STUDIO_HOST_PORT=${studio_port}
FORGE_MARKET_POSTGRES_HOST_PORT=${postgres_port}
FORGE_MARKET_API_ONLY=1
INCLUDE_STUDIO_UI=0
EOF
      fi
    elif [[ -f .env.example ]]; then
      cp .env.example .env
      log "created .env from .env.example — review secrets before production"
    else
      cat >.env <<EOF
FORGE_MARKET_ROOT=${FORGE_MARKET_ROOT}
POSTGRES_USER=forge_market
POSTGRES_PASSWORD=forge_market_dev
POSTGRES_DB=forge_market
FORGE_MARKET_DATABASE_URL=postgresql://forge_market:forge_market_dev@postgres:5432/forge_market
FORGE_MARKET_STUDIO_HOST_PORT=${studio_port}
FORGE_MARKET_POSTGRES_HOST_PORT=${postgres_port}
EOF
    fi
  fi
  if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    set -a && source "$ENV_FILE" && set +a
  fi
  if [[ "$FORGE_MARKET_ENV" != "dev" && -f "$GRANITE_MARKET_ENV" ]]; then
    # shellcheck disable=SC1090
    set -a && source "$GRANITE_MARKET_ENV" && set +a
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
  _persist_compose_env_key FORGE_MARKET_SEC_CONTACT "${FORGE_MARKET_SEC_CONTACT:-}"
  if [[ -n "${FORGE_MARKET_APP_IMAGE:-}" ]]; then
    _persist_compose_env_key FORGE_MARKET_APP_IMAGE "${FORGE_MARKET_APP_IMAGE}"
  fi
  local git_sha12
  git_sha12="$(_resolve_git_sha12)"
  if [[ -n "$git_sha12" ]]; then
    export FORGE_MARKET_GIT_SHA="$git_sha12"
    _persist_compose_env_key FORGE_MARKET_GIT_SHA "$git_sha12"
  fi
  if docker volume inspect "$pgdata_vol" &>/dev/null; then
    if grep -q '^POSTGRES_PASSWORD=change-me' .env 2>/dev/null; then
      log "repair compose .env postgres credentials for existing pgdata volume"
      sed -i 's|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=forge_market_dev|' .env
      sed -i 's|^FORGE_MARKET_DATABASE_URL=.*|FORGE_MARKET_DATABASE_URL=postgresql://forge_market:forge_market_dev@postgres:5432/forge_market|' .env
    fi
  fi
  if [[ -f "/home/administrator/forge-market/studio-server/studio_server.py" ]]; then
    FORGE_MARKET_ROOT="/home/administrator/forge-market"
    export FORGE_MARKET_ROOT
    if grep -q '^FORGE_MARKET_ROOT=' .env 2>/dev/null; then
      sed -i "s|^FORGE_MARKET_ROOT=.*|FORGE_MARKET_ROOT=${FORGE_MARKET_ROOT}|" .env
    fi
  fi
}

_ensure_git_fallback_clone() {
  local fallback="$1"
  local git_remote="${FORGE_MARKET_GIT_REMOTE:-https://github.com/autowww/forge-market.git}"
  [[ -n "$fallback" ]] || return 1
  if [[ -d "$fallback/.git" ]]; then
    return 0
  fi
  if [[ -e "$fallback" ]]; then
    local backup="${fallback}.stale-$(date -u +%Y%m%dT%H%M%SZ)"
    log "replacing non-git forge-market path ${fallback} (backup ${backup})"
    mv "$fallback" "$backup" || return 1
  fi
  log "cloning forge-market into ${fallback} from ${git_remote}"
  mkdir -p "$(dirname "$fallback")"
  git clone --origin origin "$git_remote" "$fallback" || return 1
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

_rsync_forge_market_tree() {
  local src="$1"
  local dst="$2"
  local -a rsync_args=(-a)
  if [[ "${FORGE_MARKET_RSYNC_DELETE:-}" == "1" ]]; then
    rsync_args+=(--delete)
  else
    log "rsync overlay (no --delete) — host-only paths under ${dst} are preserved"
  fi
  rsync "${rsync_args[@]}" \
    --exclude .git/ \
    --exclude /data/ \
    --exclude .venv/ \
    --exclude studio-ui/node_modules/ \
    --exclude desktop/node_modules/ \
    "${src}/" "${dst}/"
}

sync_forge_market_checkout() {
  ensure_vendor_lcdl
  local fallback="${FORGE_MARKET_GIT_FALLBACK_ROOT:-}"
  local git_ref="${FORGE_MARKET_GIT_REF:-}"
  local sync_src=""

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

  if [[ -n "$git_ref" ]]; then
    fallback="${fallback:-/home/administrator/Code/forge-market}"
    _ensure_git_fallback_clone "$fallback" || log "WARN: could not clone git fallback at ${fallback}"
    if [[ -d "$fallback/.git" ]]; then
      if ! _sync_git_tree "$fallback"; then
        log "WARN: fallback git sync failed — rsync may be stale"
      fi
      sync_src="$fallback"
    fi
  elif [[ -d "${FORGE_MARKET_ROOT}/.git" ]]; then
    log "syncing git checkout at ${FORGE_MARKET_ROOT}"
    if ! _sync_git_tree "${FORGE_MARKET_ROOT}"; then
      log "WARN: forge-market git sync failed — using tree as-is"
    fi
    return 0
  fi

  if [[ -z "$sync_src" && -n "$fallback" && -d "$fallback/.git" ]]; then
    log "syncing fallback git checkout at ${fallback}"
    if ! _sync_git_tree "$fallback"; then
      log "WARN: fallback git sync failed — rsync may be stale"
    fi
    sync_src="$fallback"
  fi

  if [[ -n "$sync_src" ]]; then
    if [[ "$(readlink -f "$sync_src" 2>/dev/null || printf '%s' "$sync_src")" == "$(readlink -f "${FORGE_MARKET_ROOT}" 2>/dev/null || printf '%s' "${FORGE_MARKET_ROOT}")" ]]; then
      log "forge-market deploy root matches git source ${sync_src}"
      return 0
    fi
    log "overlay ${FORGE_MARKET_ROOT} from git source ${sync_src}"
    mkdir -p "${FORGE_MARKET_ROOT}"
    _rsync_forge_market_tree "$sync_src" "${FORGE_MARKET_ROOT}"
    return 0
  fi

  log "forge-market root is not a git checkout — using tree as-is"
}

ensure_vendor_lcdl() {
  local vend="${FORGE_MARKET_ROOT}/vendor/forge-lcdl/src/forge_lcdl"
  if [[ -f "${vend}/__init__.py" ]]; then
    return 0
  fi
  local candidate
  for candidate in \
    "${FORGE_MARKET_ROOT}/../forge-lcdl/src" \
    "/home/administrator/Code/forge-lcdl/src" \
    "$HOME/Code/forge-lcdl/src" \
    "$FLEET_ROOT/../forge-lcdl/src"; do
    if [[ -f "${candidate}/forge_lcdl/__init__.py" ]]; then
      log "staging vendor forge-lcdl from ${candidate}"
      mkdir -p "${FORGE_MARKET_ROOT}/vendor/forge-lcdl"
      rsync -a "${candidate}/" "${FORGE_MARKET_ROOT}/vendor/forge-lcdl/src/"
      return 0
    fi
  done
  log "WARN: forge-lcdl vendor missing — market-app image may fail at runtime"
}

reconcile_postgres_password() {
  local pass="${POSTGRES_PASSWORD:-forge_market_dev}"
  [[ -n "$pass" ]] || return 0
  cd "$MARKET_STUDIO_ROOT"
  local -a files
  compose_file_args files
  log "reconcile postgres role password with compose .env"
  compose "${files[@]}" exec -T postgres \
    psql -U "${POSTGRES_USER:-forge_market}" -d postgres \
    -c "ALTER USER ${POSTGRES_USER:-forge_market} PASSWORD '${pass}';" \
    2>/dev/null || log "WARN: postgres password reconcile skipped (role may already match)"
}

compose_file_args() {
  local -n out=$1
  out=(-f compose.yaml)
  if [[ -n "$COMPOSE_FILES" ]]; then
    IFS=',' read -ra overlays <<<"$COMPOSE_FILES"
    for ov in "${overlays[@]}"; do
      ov="${ov#"${ov%%[![:space:]]*}"}"
      ov="${ov%"${ov##*[![:space:]]}"}"
      [[ -n "$ov" ]] || continue
      [[ -f "$ov" ]] || die "compose overlay missing: $ov"
      out+=(-f "$ov")
    done
  fi
}

wait_postgres_ready() {
  local -a files
  compose_file_args files
  log "waiting for postgres health"
  local attempt
  for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    if compose "${files[@]}" exec -T postgres \
      pg_isready -U "${POSTGRES_USER:-forge_market}" -d "${POSTGRES_DB:-forge_market}" \
      2>/dev/null; then
      return 0
    fi
    sleep 2
  done
  die "postgres not ready after rollout start"
}

build_market_app_image() {
  if [[ "${FORGE_MARKET_SKIP_BUILD:-0}" == "1" ]]; then
    log "skip docker build (FORGE_MARKET_SKIP_BUILD=1)"
    if [[ -n "${FORGE_MARKET_APP_IMAGE:-}" ]]; then
      log "using promoted image ${FORGE_MARKET_APP_IMAGE}"
      if ! docker image inspect "${FORGE_MARKET_APP_IMAGE}" &>/dev/null; then
        die "promoted image not present locally: ${FORGE_MARKET_APP_IMAGE}"
      fi
      local promoted_digest
      promoted_digest="$(docker image inspect --format='{{.Id}}' "${FORGE_MARKET_APP_IMAGE}" 2>/dev/null || true)"
      log "promoted image digest=${promoted_digest}"
    fi
    return 0
  fi
  cd "$MARKET_STUDIO_ROOT"
  if [[ -f "${FORGE_MARKET_ROOT}/studio-server/studio_server.py" ]]; then
    date -u +"%Y-%m-%dT%H:%M:%SZ" >"${FORGE_MARKET_ROOT}/.forge-deploy-stamp"
  fi
  local -a files
  compose_file_args files
  local git_sha12
  git_sha12="$(_resolve_git_sha12)"
  if [[ -n "$git_sha12" ]]; then
    export FORGE_MARKET_GIT_SHA="$git_sha12"
    _persist_compose_env_key FORGE_MARKET_GIT_SHA "$git_sha12"
  fi
  log "building market-app image (context $FORGE_MARKET_ROOT git_sha=${git_sha12:-unknown})"
  local -a build_cmd=(build market-app)
  if [[ "${FORGE_MARKET_DOCKER_BUILD_NO_CACHE:-}" == "1" ]]; then
    build_cmd=(build --no-cache market-app)
  fi
  if [[ -n "${FORGE_MARKET_GIT_SHA:-}" ]]; then
    build_cmd+=(--build-arg "FORGE_MARKET_GIT_SHA=${FORGE_MARKET_GIT_SHA}")
  fi
  compose "${files[@]}" "${build_cmd[@]}"
  local built_image="${FORGE_MARKET_APP_IMAGE:-forge-market-app:studio}"
  if [[ -n "$git_sha12" ]]; then
    local sha_tag="forge-market-app:${git_sha12}"
    log "tagging ${built_image} as ${sha_tag}"
    docker tag "$built_image" "$sha_tag"
    local image_digest
    image_digest="$(docker image inspect --format='{{.Id}}' "$sha_tag" 2>/dev/null || true)"
    log "built image ${sha_tag} digest=${image_digest}"
  fi
}

start_postgres_service() {
  cd "$MARKET_STUDIO_ROOT"
  local -a files
  compose_file_args files
  log "starting postgres service"
  compose "${files[@]}" up -d postgres
  wait_postgres_ready
  reconcile_postgres_password
}

run_postgres_schema_migrate() {
  if [[ "${FORGE_MARKET_RUN_SCHEMA_MIGRATE:-1}" != "1" ]]; then
    log "skip postgres schema migrate (FORGE_MARKET_RUN_SCHEMA_MIGRATE=${FORGE_MARKET_RUN_SCHEMA_MIGRATE:-0})"
    return 0
  fi
  cd "$MARKET_STUDIO_ROOT"
  local -a files
  compose_file_args files
  log "stopping market-app before postgres schema migrate"
  compose "${files[@]}" stop market-app 2>/dev/null || true
  log "running postgres schema migrate (forge_market.db.migrate upgrade)"
  compose "${files[@]}" run --rm --no-deps market-app python -m forge_market.db.migrate upgrade
}

start_market_app_stack() {
  cd "$MARKET_STUDIO_ROOT"
  local -a files
  compose_file_args files
  log "starting forge-market-studio stack"
  compose "${files[@]}" up -d
  reconcile_postgres_password
}

deploy_compose_stack() {
  build_market_app_image
  start_postgres_service
  run_postgres_schema_migrate
  start_market_app_stack
}

register_fleet_service() {
  local fleet_port="${FLEET_LOCAL_PORT:-18766}"
  local fleet_token="${FLEET_BEARER_TOKEN:-}"
  local service_id="market-studio"
  local service_label="Granite Market Studio"
  if [[ "$FORGE_MARKET_ENV" == "dev" ]]; then
    service_id="market-studio-dev"
    service_label="Granite Market Studio (DEV)"
  fi
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
  log "registering ${service_id} service with Fleet"
  curl -fsS -X POST "http://127.0.0.1:${fleet_port}/v1/container-services" \
    -H "Authorization: Bearer ${fleet_token}" \
    -H "Content-Type: application/json" \
    -d "{\"id\":\"${service_id}\",\"type_id\":\"forge_market_studio\",\"compose_root\":\"${MARKET_STUDIO_ROOT}\",\"compose_files\":${cf_json},\"label\":\"${service_label}\"}" \
    2>/dev/null || log "Fleet registration skipped (may already exist)"
}

smoke() {
  local port="${FORGE_MARKET_STUDIO_HOST_PORT:-19792}"
  local url="http://127.0.0.1:${port}/health"
  log "smoke: GET $url"
  local attempt
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    local body
    body="$(curl -fsS "$url" 2>/dev/null || true)"
    if echo "$body" | grep -q forge-market-studio; then
      if command -v jq >/dev/null 2>&1; then
        local sv sh
        sv="$(echo "$body" | jq -r '.schema_version // empty')"
        sh="$(echo "$body" | jq -r '.schema_head // empty')"
        if [[ -n "$sv" && -n "$sh" ]]; then
          log "smoke schema_version=$sv schema_head=$sh"
          if [[ "$sv" != "$sh" ]]; then
            die "schema version mismatch (applied=$sv head=$sh)"
          fi
        fi
      fi
      return 0
    fi
    sleep 2
  done
  log "market-app logs (last 80 lines):"
  (
    cd "$MARKET_STUDIO_ROOT"
    local -a files
    compose_file_args files
    compose "${files[@]}" logs --no-color --tail=80 market-app 2>&1 | tail -80
  ) || true
  die "health check failed for $url"
}

ensure_external_volumes() {
  cd "$MARKET_STUDIO_ROOT"
  # shellcheck disable=SC1091
  [[ -f .env ]] && set -a && source .env && set +a
  local pgdata appdata
  pgdata="${FORGE_MARKET_PGDATA_VOLUME:-$(_default_pgdata_volume)}"
  if [[ "$FORGE_MARKET_ENV" == "dev" ]]; then
    appdata="${FORGE_MARKET_APPDATA_VOLUME:-forge_market_studio_dev_data}"
  else
    appdata="${FORGE_MARKET_APPDATA_VOLUME:-forge_market_studio_data}"
  fi
  for vol in "$pgdata" "$appdata"; do
    if docker volume inspect "$vol" &>/dev/null; then
      log "volume exists: $vol"
    else
      log "creating volume: $vol"
      docker volume create "$vol" >/dev/null
    fi
  done
}

main() {
  command -v docker >/dev/null || die "docker missing"
  command -v curl >/dev/null || die "curl missing"
  ensure_env_file
  ensure_external_volumes
  ensure_paths
  ensure_vendor_lcdl
  sync_forge_market_checkout
  deploy_compose_stack
  register_fleet_service
  smoke
  log "rollout complete (env=${FORGE_MARKET_ENV} market studio loopback :${FORGE_MARKET_STUDIO_HOST_PORT:-$(_default_studio_host_port)})"
  if [[ "$FORGE_MARKET_ENV" == "dev" ]]; then
    bash "$FLEET_ROOT/scripts/register-market-studio-dev-gateway.sh" || log "DEV gateway registration skipped"
  else
    log "optional Granite host edge: forge-market/scripts/granite/install-granite-edge-plane.sh"
    log "optional Granite scheduler: forge-fleet/scripts/install-granite-market-scheduler.sh"
  fi
}

main "$@"
