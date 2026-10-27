#!/usr/bin/env bash
# Fleet-local rollout for Open WebUI on Granite (compose only — no SSH).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEPLOY="${OPEN_WEBUI_DEPLOY_ROOT:-$REPO_ROOT/deploy/open-webui}"
COMPOSE_FILES=(-f "$DEPLOY/compose.yaml" -f "$DEPLOY/compose.granite.yaml")

cd "$DEPLOY"
[[ -f .env ]] || { echo "copy .env.example to .env and set secrets" >&2; exit 1; }

set -a
# shellcheck disable=SC1091
source .env
set +a

docker volume create "${OPEN_WEBUI_PGDATA_VOLUME:-forge_open_webui_pgdata}" 2>/dev/null || true
docker volume create "${OPEN_WEBUI_DATA_VOLUME:-forge_open_webui_data}" 2>/dev/null || true

docker compose "${COMPOSE_FILES[@]}" pull open-webui
docker compose "${COMPOSE_FILES[@]}" up -d --remove-orphans

echo "Open WebUI loopback: http://127.0.0.1:${OPEN_WEBUI_HOST_PORT:-19808}/"
echo "Next: unified Caddy OPEN_WEBUI_SITE_ADDRESS + account-plane install"
