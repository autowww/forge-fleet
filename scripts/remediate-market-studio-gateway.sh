#!/usr/bin/env bash
# Remediate Granite Market Studio app gateway via Fleet API only (no SSH).
# Brings up loopback :19792 data API behind /v1/app-gateways/market-studio.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "$ROOT/../forge-certificators/example-banks/forge-certificator-secrets.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/../forge-certificators/example-banks/forge-certificator-secrets.env"
  set +a
fi

BASE="${FORGE_FLEET_BASE_URL:-${FLEET_BASE_URL:-}}"
TOK="${FORGE_FLEET_BEARER_TOKEN:-${FLEET_BEARER_TOKEN:-}}"
GATEWAY="${FORGE_MARKET_REMOTE_API:-${BASE}/v1/app-gateways/market-studio}"
REMEDIATE_STUDIO_ROOT="${REMEDIATE_STUDIO_ROOT:-/home/administrator/.local/share/forge-fleet/deploy/forge-market-studio}"
REMEDIATE_MARKET_ROOT="${REMEDIATE_MARKET_ROOT:-/home/administrator/forge-market}"
REMEDIATE_DOCKERFILE="${REMEDIATE_DOCKERFILE:-${REMEDIATE_STUDIO_ROOT}/Dockerfile.market-app}"
FORGE_MARKET_ROOT="${FORGE_MARKET_ROOT:-}"
POLL_SEC="${REMEDIATE_POLL_SEC:-15}"
MAX_WAIT_SEC="${REMEDIATE_MAX_WAIT_SEC:-900}"

log() { printf 'remediate-market-studio-gateway: %s\n' "$*"; }
die() { log "ERROR: $*"; exit 1; }

[[ -n "$BASE" && -n "$TOK" ]] || die "set FORGE_FLEET_BASE_URL and FORGE_FLEET_BEARER_TOKEN"

fleet_post() {
  local path="$1"
  local body="${2:-{}}"
  curl -fsS --max-time 120 -X POST \
    -H "Authorization: Bearer ${TOK}" \
    -H "Content-Type: application/json" \
    -d "$body" \
    "${BASE}${path}"
}

fleet_get() {
  local path="$1"
  curl -fsS --max-time 60 -H "Authorization: Bearer ${TOK}" "${BASE}${path}"
}

log "1/5 git-self-update on Fleet host (stash dirty tree when needed)"
fleet_post /v1/admin/git-self-update '{"stash": true}' >/dev/null || log "WARN: git-self-update failed (continuing)"
sleep 8

log "2/5 sync built-in container types (forge_market_studio)"
fleet_post /v1/admin/sync-container-types '{}' | python3 -c "import json,sys; d=json.load(sys.stdin); print('added', d.get('added',[]))" || true

log "3/5 schedule market-studio compose rollout (async — docker build may take several minutes)"
ROLL_BODY="$(python3 - <<'PY'
import json, os
print(json.dumps({
  "sync": False,
  "forge_market_root": os.environ["REMEDIATE_MARKET_ROOT"],
  "forge_market_studio_root": os.environ["REMEDIATE_STUDIO_ROOT"],
  "forge_market_dockerfile": os.environ["REMEDIATE_DOCKERFILE"],
}))
PY
)"
fleet_post /v1/admin/forge-market-studio-rollout "$ROLL_BODY" | python3 -m json.tool

log "4/5 poll rollout log + gateway health (up to ${MAX_WAIT_SEC}s)"
deadline=$((SECONDS + MAX_WAIT_SEC))
while (( SECONDS < deadline )); do
  if fleet_get "${GATEWAY%/}/health" 2>/dev/null | grep -q forge-market-studio; then
    log "gateway health OK"
    fleet_get "${GATEWAY%/}/health"
    exit 0
  fi
  LOG="$(fleet_get /v1/admin/forge-market-studio-rollout-log 2>/dev/null || echo '{}')"
  echo "$LOG" | python3 - <<'PY'
import json, sys
raw = sys.stdin.read()
try:
    d = json.loads(raw)
except json.JSONDecodeError:
    print(raw[-400:])
    raise SystemExit(0)
log = (d.get("log") or "").splitlines()
for line in log[-4:]:
    if line.strip():
        print("  log:", line[:200])
PY
  sleep "$POLL_SEC"
done

log "5/5 timed out — fetch final rollout log"
fleet_get /v1/admin/forge-market-studio-rollout-log | python3 -c "import json,sys; print(json.load(sys.stdin).get('log','')[-4000:])"
die "gateway still unhealthy after ${MAX_WAIT_SEC}s"
