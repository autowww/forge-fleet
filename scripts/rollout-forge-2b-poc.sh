#!/usr/bin/env bash
# Build + (re)start the forge-2b PoC stack on a Fleet host from the git checkout.
#
#   ~/forge-fleet/scripts/rollout-forge-2b-poc.sh            # build, up -d, wait healthy
#   ~/forge-fleet/scripts/rollout-forge-2b-poc.sh --down     # compose down (volumes kept)
#
# Env file: ${FORGE_2B_ENV_FILE:-~/.config/forge-2b-poc/forge-2b.env} (see deploy/forge-2b-poc/forge-2b.env.example).
# Requires the Open WebUI compose network (default forge-open-webui_default) to exist.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY="$HERE/deploy/forge-2b-poc"
export FORGE_2B_ENV_FILE="${FORGE_2B_ENV_FILE:-$HOME/.config/forge-2b-poc/forge-2b.env}"
export OPEN_WEBUI_NETWORK="${OPEN_WEBUI_NETWORK:-forge-open-webui_default}"
export FORGE_LLM_NETWORK="${FORGE_LLM_NETWORK:-forge-llm-control-plane_default}"

compose() { docker compose -f "$DEPLOY/compose.yaml" "$@"; }

if [[ "${1:-}" == "--down" ]]; then
  compose down
  exit 0
fi

[[ -f "$FORGE_2B_ENV_FILE" ]] || { echo "missing env file $FORGE_2B_ENV_FILE (copy forge-2b.env.example)" >&2; exit 2; }
[[ -f "$DEPLOY/vendor/forge_2b/facade.py" ]] || { echo "vendor/ not synced; run scripts/sync-forge-2b-poc.sh and push" >&2; exit 2; }
for net in "$OPEN_WEBUI_NETWORK" "$FORGE_LLM_NETWORK"; do
  docker network inspect "$net" >/dev/null 2>&1 || { echo "network $net missing" >&2; exit 2; }
done

echo "[forge-2b-poc] sources: $(cat "$DEPLOY/vendor/SOURCES.txt" | tr '\n' ';')"
compose build --pull forge-dcs
compose up -d --force-recreate --remove-orphans

for i in $(seq 1 30); do
  st_dcs="$(docker inspect -f '{{.State.Health.Status}}' forge-dcs 2>/dev/null || echo missing)"
  st_2b="$(docker inspect -f '{{.State.Health.Status}}' forge-2b 2>/dev/null || echo missing)"
  if [[ "$st_dcs" == healthy && "$st_2b" == healthy ]]; then
    echo "[forge-2b-poc] healthy: forge-dcs=$st_dcs forge-2b=$st_2b"
    docker exec forge-2b python3 -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:9085/healthz',timeout=3).read().decode())"
    exit 0
  fi
  sleep 3
done
echo "[forge-2b-poc] not healthy after 90s: forge-dcs=$st_dcs forge-2b=$st_2b" >&2
docker logs --tail 40 forge-2b >&2 || true
exit 1
