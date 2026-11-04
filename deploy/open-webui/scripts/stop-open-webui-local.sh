#!/usr/bin/env bash
# Stop Open WebUI compose on non-Granite hosts (operator laptop). Idempotent.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=open-webui-host-guard.sh
source "$SCRIPT_DIR/open-webui-host-guard.sh"

if open_webui_host_allowed; then
  echo "Host is Granite-capable ($(hostname -s)); not stopping Open WebUI (use compose down manually if intended)."
  exit 0
fi

COMPOSE_FILES=(-f "$DEPLOY/compose.yaml")
if [[ -f "$DEPLOY/compose.granite.yaml" ]]; then
  COMPOSE_FILES+=(-f "$DEPLOY/compose.granite.yaml")
fi

cd "$DEPLOY"
if docker compose "${COMPOSE_FILES[@]}" ps -q 2>/dev/null | grep -q .; then
  docker compose "${COMPOSE_FILES[@]}" down --remove-orphans
  echo "Stopped Open WebUI compose on $(hostname -s)."
else
  for c in forge-open-webui forge-open-webui-postgres; do
    docker rm -f "$c" 2>/dev/null || true
  done
  echo "No Open WebUI compose project running (removed stray containers if any)."
fi
