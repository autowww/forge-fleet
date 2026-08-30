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
  local body
  if ! body="$(curl -fsS --max-time 15 "${BASE}/v1/app-gateways/${slug}/health" \
    -H "Authorization: Bearer ${TOK}" 2>/dev/null)"; then
    log "${slug}: probe failed"
    return 1
  fi
  printf '%s\n' "$body" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status', d.get('ok')), d.get('environment',{}).get('id',''))" 2>/dev/null \
    || log "${slug}: non-json health body"
}

probe_write() {
  local slug="$1"
  local code
  code="$(curl -sS -o /tmp/fm-probe-write.json -w "%{http_code}" --max-time 60 \
    -X POST "${BASE}/v1/app-gateways/${slug}/api/prices/sync" \
    -H "Authorization: Bearer ${TOK}" \
    -H "Content-Type: application/json" \
    -d '{"tickers":["NVDA"],"source":"orchestrated","interval":"1h","lookback_bars":5,"mock":true,"prepare_cdp":false}' 2>/dev/null || echo "000")"
  log "${slug} POST /api/prices/sync → HTTP ${code}"
  if [[ -f /tmp/fm-probe-write.json ]]; then
    head -c 200 /tmp/fm-probe-write.json | tr '\n' ' '
    echo
  fi
}

log "PROD health"; probe market-studio || true
log "PROD write (mock harvest)"; probe_write market-studio || true
log "DEV health"; probe market-studio-dev || true
log "DEV write (mock harvest)"; probe_write market-studio-dev || true
log "CLEAN health (if provisioned)"; probe market-studio-clean || true
log "CLEAN write (if provisioned)"; probe_write market-studio-clean || true

log "done — inspect failures above; provision clean via POST /v1/environments if missing"
