#!/usr/bin/env bash
# Wire web bridges to per-tenant Lenses container CDP (requires lenses gateway on loopback :8090).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BEARER_DIR="${FORGE_OPEN_WEBUI_BEARER_DIR:-${HOME}/.config/forge-open-webui}"
mkdir -p "$BEARER_DIR"
chmod 700 "$BEARER_DIR"

OUT="${BEARER_DIR}/lenses-tenant-gateway.env"
if [[ ! -s "$OUT" ]]; then
  umask 077
  printf 'FORGE_WEB_BRIDGE_TENANT_GATEWAY_URL=http://127.0.0.1:8090\nFORGE_WEB_BRIDGE_TENANT_GATEWAY_SECRET=%s\nFORGE_WEB_BRIDGE_TENANT_ONLY=1\n' \
    "$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" >"$OUT"
  chmod 600 "$OUT"
  echo "created $OUT"
fi

GW_STATE="${LENSES_GATEWAY_STATE:-${HOME}/.local/share/forge-lenses-gateway}"
GW_ENV="${GW_STATE}/profile-api.env"
secret="$(grep FORGE_WEB_BRIDGE_TENANT_GATEWAY_SECRET "$OUT" | cut -d= -f2-)"
umask 077
printf 'LENSES_GATEWAY_PROFILE_SECRET=%s\n' "$secret" >"$GW_ENV"
chmod 600 "$GW_ENV"
echo "wrote LENSES_GATEWAY_PROFILE_SECRET to $GW_ENV"
echo "Restart forge-lenses-gateway with: EnvironmentFile=$GW_ENV"
echo "Re-run scripts/install-open-webui-account-plane.sh (units load $OUT via EnvironmentFile=-)"