#!/usr/bin/env bash
# Enable Granite Fleet edge-cache orchestration via local Playwright (Settings → Edge).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

for f in \
  "$ROOT/../forge-certificators/example-banks/forge-certificator-secrets.env" \
  "$ROOT/../forge-matrix/.env" \
  "$ROOT/../forge-knowledge-assistant/.env.local"; do
  if [[ -f "$f" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$f"
    set +a
  fi
done

LOCAL_FLEET_ENV="${HOME}/.config/forge-fleet/forge-fleet.env"
if [[ -f "$LOCAL_FLEET_ENV" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$LOCAL_FLEET_ENV"
  set +a
fi

: "${FORGE_FLEET_BASE_URL:?Set FORGE_FLEET_BASE_URL (e.g. certificator secrets)}"
: "${FORGE_FLEET_BEARER_TOKEN:?Set FORGE_FLEET_BEARER_TOKEN}"
: "${CLOUDFLARE_API_TOKEN:?Set CLOUDFLARE_API_TOKEN (e.g. forge-matrix/.env)}"
export CF_ZONE_ID="${CF_ZONE_ID:-a930a3d1ec96b9bcaa0ab388ddad6274}"

: "${FLEET_BEARER_TOKEN:?Set FLEET_BEARER_TOKEN in ~/.config/forge-fleet/forge-fleet.env}"

if [[ ! -d node_modules/playwright ]]; then
  npm install
  npx playwright install chromium
fi

exec node "$ROOT/scripts/enable-granite-edge-cache-playwright.mjs"
