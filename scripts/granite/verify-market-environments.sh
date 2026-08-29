#!/usr/bin/env bash
# Verify Market Studio environments on Granite (DEV rollout + clean health probes).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ -f "$ROOT/../forge-certificators/example-banks/forge-certificator-secrets.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/../forge-certificators/example-banks/forge-certificator-secrets.env"
  set +a
fi

BASE="${FORGE_FLEET_BASE_URL:-}"
TOK="${FORGE_FLEET_BEARER_TOKEN:-}"
[[ -n "$BASE" && -n "$TOK" ]] || { echo "set FORGE_FLEET_BASE_URL and FORGE_FLEET_BEARER_TOKEN"; exit 1; }

log() { printf 'verify-market-environments: %s\n' "$*"; }

log "DEV rollout"
curl -fsS -X POST "${BASE}/v1/admin/forge-market-studio-rollout" \
  -H "Authorization: Bearer ${TOK}" \
  -H "Content-Type: application/json" \
  -d '{"forge_market_env":"dev"}' | python3 -m json.tool

log "waiting 90s for DEV rollout"
sleep 90

probe() {
  local slug="$1"
  curl -fsS --max-time 10 "${BASE}/v1/app-gateways/${slug}/health" \
    -H "Authorization: Bearer ${TOK}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status', d.get('ok')), d.get('environment',{}).get('id',''))"
}

log "PROD health"; probe market-studio || true
log "DEV health"; probe market-studio-dev || true
log "CLEAN health (if provisioned)"; probe market-studio-clean || true

log "done — inspect failures above; provision clean via POST /v1/environments if missing"
