#!/usr/bin/env bash
# Ship forge-lcdl (pyproject.toml + src) to Granite without scp/rsync — uses Fleet HTTPS.
#
# Usage (from forge-fleet/ or Code root):
#   set -a; source forge-certificators/example-banks/forge-certificator-secrets.env; set +a
#   deploy/open-webui/scripts/push-forge-lcdl-via-fleet.sh
#
# Optional: FORGE_LCDL_SRC=~/Code/forge-lcdl  FORGE_FLEET_BASE_URL  FORGE_FLEET_BEARER_TOKEN
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LCDL_SRC="${FORGE_LCDL_SRC:-$HOME/Code/forge-lcdl}"
BASE="${FORGE_FLEET_BASE_URL:-https://granite.forgedc.net}"
BASE="${BASE%/}"
TOKEN="${FORGE_FLEET_BEARER_TOKEN:-}"

[[ -f "$LCDL_SRC/pyproject.toml" ]] || { echo "missing $LCDL_SRC/pyproject.toml" >&2; exit 1; }
[[ -n "$TOKEN" ]] || { echo "set FORGE_FLEET_BEARER_TOKEN" >&2; exit 2; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

cp "$LCDL_SRC/pyproject.toml" "$WORK/"
cp -a "$LCDL_SRC/src" "$WORK/src"
cat >"$WORK/.forge_migration_manifest.json" <<'EOF'
{"schema_version":1,"flags":{}}
EOF

BUNDLE="$WORK/forge-lcdl-bundle.tgz"
tar czf "$BUNDLE" -C "$WORK" .forge_migration_manifest.json pyproject.toml src
SHA=$(sha256sum "$BUNDLE" | awk '{print $1}')
BYTES=$(wc -c <"$BUNDLE" | tr -d ' ')

echo "bundle bytes=$BYTES sha256=$SHA"

MIG_JSON=$(curl -fsS -X POST "$BASE/v1/migrations" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source_label":"open-webui-forge-lcdl","target_label":"granite","meta":{"app":"open-webui"}}')
MID=$(python3 -c "import json,sys; print(json.load(sys.stdin)['id'])" <<<"$MIG_JSON")
echo "migration_id=$MID"

# Single PUT and large chunks hit Cloudflare 413; use 512 KiB chunks.
CHUNK_SIZE=65536
CHUNK_COUNT=$(( (BYTES + CHUNK_SIZE - 1) / CHUNK_SIZE ))
curl -fsS -X POST "$BASE/v1/migrations/$MID/data-bundle/upload-session" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"sha256\":\"$SHA\",\"total_bytes\":$BYTES,\"chunk_size\":$CHUNK_SIZE}" >/dev/null

split -b "$CHUNK_SIZE" -d -a 3 "$BUNDLE" "$WORK/chunk."
for i in $(seq 0 $((CHUNK_COUNT - 1))); do
  PART=$(printf '%s/chunk.%03d' "$WORK" "$i")
  curl -fsS -X PUT "$BASE/v1/migrations/$MID/data-bundle/chunks/$i" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/octet-stream" \
    --data-binary @"$PART"
  echo " chunk $i/$((CHUNK_COUNT - 1)) ok"
done

curl -fsS -X POST "$BASE/v1/migrations/$MID/data-bundle/finalize" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}' | python3 -m json.tool

EXT="\$HOME/.local/share/forge-fleet/migration-bundles/$MID/extracted"
cat <<EOF

Uploaded. On Granite (short ssh — no scp):

  ssh granite 'rm -rf ~/forge-lcdl && mkdir -p ~/forge-lcdl && cp -a $EXT/pyproject.toml $EXT/src ~/forge-lcdl/'

Then install bridges:

  ssh granite 'python3 -m pip install -e ~/forge-lcdl[playwright] && python3 -m pip install -e ~/forge-fleet/deploy/open-webui/bridge && python3 -m playwright install chromium'

EOF
