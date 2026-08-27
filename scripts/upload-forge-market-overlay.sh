#!/usr/bin/env bash
# Upload a minimal forge-market overlay (expansion routes + deps only).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FM_ROOT="${FORGE_MARKET_ROOT:-$ROOT/../forge-market}"
REF="${FORGE_MARKET_GIT_REF:-feature/fm-semiconductor-pdca}"
DEST="${FORGE_MARKET_DEPLOY_ROOT:-/home/administrator/forge-market}"

PATHS=(
  studio-server/studio_server.py
  studio-server/pipeline_api.py
  studio-server/remote_api_proxy.py
  studio-server/requirements.txt
  src/forge_market/granite_client.py
  src/forge_market/granite_llm_queue.py
  src/forge_market/analysis/narrative_enrich/enrich_cycle.py
  src/forge_market/analysis/narrative_enrich/extractor_expansion
  src/forge_market/analysis/narrative_enrich/observation_quality/judge.py
  tools/run_extractor_expansion.py
)

if [[ -f "$ROOT/../secrets/forge-fleet-secrets.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/../secrets/forge-fleet-secrets.env"
  set +a
fi
if [[ -f "$ROOT/../forge-certificators/example-banks/forge-certificator-secrets.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/../forge-certificators/example-banks/forge-certificator-secrets.env"
  set +a
fi

BASE="${FORGE_FLEET_BASE_URL:-${FLEET_BASE_URL:-}}"
TOK="${FORGE_FLEET_BEARER_TOKEN:-${FLEET_BEARER_TOKEN:-}}"
[[ -n "$BASE" && -n "$TOK" ]] || {
  echo "set FORGE_FLEET_BASE_URL and FORGE_FLEET_BEARER_TOKEN" >&2
  exit 1
}

[[ -d "$FM_ROOT/.git" ]] || {
  echo "forge-market git checkout missing at $FM_ROOT" >&2
  exit 1
}

TMP="$(mktemp /tmp/fm-overlay-min.XXXXXX.tgz)"
trap 'rm -f "$TMP"' EXIT
git -C "$FM_ROOT" archive --format=tar.gz -o "$TMP" "$REF" "${PATHS[@]}"

echo "uploading minimal overlay $(du -h "$TMP" | awk '{print $1}') ref=$REF dest=$DEST"
curl -fsS -X PUT \
  -H "Authorization: Bearer ${TOK}" \
  -H "Content-Type: application/gzip" \
  --data-binary @"$TMP" \
  "${BASE}/v1/admin/forge-market-source-overlay?dest_root=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$DEST")" \
  | python3 -m json.tool

echo "schedule docker rebuild rollout"
curl -fsS -X POST "${BASE}/v1/admin/forge-market-studio-rollout" \
  -H "Authorization: Bearer ${TOK}" \
  -H "Content-Type: application/json" \
  -d "{\"sync\": false, \"forge_market_root\": \"${DEST}\", \"forge_market_studio_root\": \"/home/administrator/.local/share/forge-fleet/deploy/forge-market-studio\", \"forge_market_docker_build_no_cache\": \"1\"}" \
  | python3 -m json.tool
