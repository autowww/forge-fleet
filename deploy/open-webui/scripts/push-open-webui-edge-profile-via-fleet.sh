#!/usr/bin/env bash
# Upload a packed Edge profile tarball to Granite via Fleet HTTPS (no scp).
set -euo pipefail

BUNDLE="${1:?usage: $0 /path/to/open-webui-profile-SLUG.tgz}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
KA_ENV="$ROOT/../forge-certificators/example-banks/forge-certificator-secrets.env"
[[ -f "$ROOT/../forge-certificators/example-banks/forge-certificator-secrets.env" ]] && KA_ENV="$ROOT/../forge-certificators/example-banks/forge-certificator-secrets.env"
if [[ -z "${FORGE_FLEET_BEARER_TOKEN:-}" && -f "$KA_ENV" ]]; then
  FORGE_FLEET_BEARER_TOKEN="$(grep -E '^FORGE_FLEET_BEARER_TOKEN=' "$KA_ENV" | head -1 | cut -d= -f2- | tr -d '\r')"
fi
BASE="${FORGE_FLEET_BASE_URL:-https://granite.forgedc.net}"
BASE="${BASE%/}"
TOKEN="${FORGE_FLEET_BEARER_TOKEN:-}"
[[ -n "$TOKEN" ]] || { echo "set FORGE_FLEET_BEARER_TOKEN" >&2; exit 2; }
[[ -f "$BUNDLE" ]] || { echo "missing $BUNDLE" >&2; exit 1; }

SHA=$(sha256sum "$BUNDLE" | awk '{print $1}')
BYTES=$(wc -c <"$BUNDLE" | tr -d ' ')
CHUNK_SIZE=65536

MIG_JSON=$(curl -fsS -X POST "$BASE/v1/migrations" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source_label":"open-webui-edge-profile","target_label":"granite"}')
MID=$(python3 -c "import json,sys; print(json.load(sys.stdin)['id'])" <<<"$MIG_JSON")

curl -fsS -X POST "$BASE/v1/migrations/$MID/data-bundle/upload-session" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"sha256\":\"$SHA\",\"total_bytes\":$BYTES,\"chunk_size\":$CHUNK_SIZE}" >/dev/null

WORK="$(mktemp -d)"
split -b "$CHUNK_SIZE" -d -a 3 "$BUNDLE" "$WORK/chunk."
n=0
for PART in "$WORK"/chunk.*; do
  curl -fsS -X PUT "$BASE/v1/migrations/$MID/data-bundle/chunks/$n" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/octet-stream" \
    --data-binary @"$PART" >/dev/null
  n=$((n + 1))
done
rm -rf "$WORK"

curl -fsS -X POST "$BASE/v1/migrations/$MID/data-bundle/finalize" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}' >/dev/null

echo "migration_id=$MID"
echo "On Granite (as administrator):"
echo "  $SCRIPT_DIR/install-open-webui-edge-profile-from-fleet.sh $MID"
