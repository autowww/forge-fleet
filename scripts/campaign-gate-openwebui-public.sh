#!/usr/bin/env bash
# Campaign gate: public Open WebUI health (Mercury after cutover).
set -euo pipefail
URL="${FORGE_OPEN_WEBUI_URL:-https://webui.forgedc.net}"
curl -fsS "${URL}/api/models" -H "Authorization: Bearer ${OPENWEBUI_API_KEY:?OPENWEBUI_API_KEY required}" | head -c 200
echo
echo "OK: ${URL}/api/models"