#!/usr/bin/env bash
# Register Fleet app gateway for any Market Studio env (prod, dev, clean, …).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FORGE_MARKET_ENV="${FORGE_MARKET_ENV:-prod}"

if [[ -f "$ROOT/../forge-certificators/example-banks/forge-certificator-secrets.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/../forge-certificators/example-banks/forge-certificator-secrets.env"
  set +a
fi

CFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/forge-fleet"
if [[ -f "$CFG_DIR/forge-fleet.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$CFG_DIR/forge-fleet.env"
  set +a
fi

BASE="${FORGE_FLEET_BASE_URL:-${FLEET_BASE_URL:-http://127.0.0.1:${FLEET_LOCAL_PORT:-18766}}}"
TOK="${FORGE_FLEET_BEARER_TOKEN:-${FLEET_BEARER_TOKEN:-}}"
COMPOSE_ROOT="${FORGE_MARKET_STUDIO_ROOT:-}"

if [[ -z "$COMPOSE_ROOT" ]]; then
  COMPOSE_ROOT="$(cd "$ROOT" && python3 -c "
from pathlib import Path
from fleet_server.market_studio_rollout_env import compose_root_for_env
import os
print(compose_root_for_env(Path('${ROOT}'), os.environ.get('FORGE_MARKET_ENV','prod')))
")"
fi

SERVICE_ID="$(cd "$ROOT" && python3 -c "
from fleet_server.market_studio_rollout_env import rollout_identity
import os
print(rollout_identity(os.environ.get('FORGE_MARKET_ENV','prod'))[0])
")"

UPSTREAM="${FORGE_MARKET_GATEWAY_UPSTREAM:-http://127.0.0.1:${FORGE_MARKET_STUDIO_HOST_PORT:-19792}}"

log() { printf 'register-market-studio-env-gateway: %s\n' "$*"; }
die() { log "ERROR: $*"; exit 1; }

[[ -n "$TOK" ]] || die "set FLEET_BEARER_TOKEN or FORGE_FLEET_BEARER_TOKEN"

PAYLOAD="{\"upstream\":\"${UPSTREAM}\",\"inject_bearer\":true,\"app_bearer_env\":\"FORGE_MARKET_STUDIO_API_TOKEN\""
if [[ "$FORGE_MARKET_ENV" == "prod" || "$FORGE_MARKET_ENV" == "production" ]]; then
  PAYLOAD="${PAYLOAD},\"compose_root\":\"${COMPOSE_ROOT}\""
fi
PAYLOAD="${PAYLOAD}}"

log "PUT ${BASE}/v1/app-gateways/${SERVICE_ID} upstream=${UPSTREAM} env=${FORGE_MARKET_ENV}"
curl -fsS -X PUT \
  -H "Authorization: Bearer ${TOK}" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" \
  "${BASE}/v1/app-gateways/${SERVICE_ID}" | python3 -m json.tool

log "gateway registered — health probe: ${BASE}/v1/app-gateways/${SERVICE_ID}/health"
