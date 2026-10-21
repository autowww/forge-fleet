#!/usr/bin/env bash
# Register Market Studio hot GET paths on the Fleet app gateway edge-cache API.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_ID="${1:-${FORGE_MARKET_GATEWAY_ID:-market-studio}}"

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
FM_ROOT="${FORGE_MARKET_STUDIO_ROOT:-$ROOT/../forge-market}"

log() { printf 'register-market-studio-edge-cache: %s\n' "$*"; }
die() { log "ERROR: $*"; exit 1; }

[[ -n "$TOK" ]] || die "set FLEET_BEARER_TOKEN or FORGE_FLEET_BEARER_TOKEN"
[[ -d "$FM_ROOT/src/forge_market" ]] || die "forge-market checkout not found at $FM_ROOT"

BODY="$(PYTHONPATH="${FM_ROOT}/src" python3 -c 'from forge_market.operator.fleet_edge_cache import registration_body; import json; print(json.dumps(registration_body()))')"

log "PUT ${BASE}/v1/app-gateways/${SERVICE_ID}/edge-cache"
curl -fsS -X PUT \
  -H "Authorization: Bearer ${TOK}" \
  -H "Content-Type: application/json" \
  -d "$BODY" \
  "${BASE}/v1/app-gateways/${SERVICE_ID}/edge-cache" | python3 -m json.tool

log "edge-cache registered for ${SERVICE_ID}"
