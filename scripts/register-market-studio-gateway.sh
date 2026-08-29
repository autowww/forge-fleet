#!/usr/bin/env bash
# Register Fleet app gateway for PROD Market Studio (loopback :19792).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

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
SERVICE_ID="${FORGE_MARKET_GATEWAY_ID:-market-studio}"
UPSTREAM="${FORGE_MARKET_GATEWAY_UPSTREAM:-http://127.0.0.1:${FORGE_MARKET_STUDIO_HOST_PORT:-19792}}"
COMPOSE_ROOT="${FORGE_MARKET_STUDIO_ROOT:-$ROOT/deploy/forge-market-studio}"

log() { printf 'register-market-studio-gateway: %s\n' "$*"; }
die() { log "ERROR: $*"; exit 1; }

[[ -n "$TOK" ]] || die "set FLEET_BEARER_TOKEN or FORGE_FLEET_BEARER_TOKEN"

log "PUT ${BASE}/v1/app-gateways/${SERVICE_ID} upstream=${UPSTREAM}"
curl -fsS -X PUT \
  -H "Authorization: Bearer ${TOK}" \
  -H "Content-Type: application/json" \
  -d "{\"upstream\":\"${UPSTREAM}\",\"inject_bearer\":true,\"app_bearer_env\":\"FORGE_MARKET_STUDIO_API_TOKEN\",\"compose_root\":\"${COMPOSE_ROOT}\"}" \
  "${BASE}/v1/app-gateways/${SERVICE_ID}" | python3 -m json.tool

log "gateway registered — health probe: ${BASE}/v1/app-gateways/${SERVICE_ID}/health"
