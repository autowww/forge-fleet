#!/usr/bin/env bash
# Build + (re)start the forge-squid stack on a Fleet host from the git checkout.
#
#   POST /v1/managed-services/forge-squid/rollout  {"forge_squid_dce_mode":"on","forge_squid_skip_build":"1"}
#   GET  /v1/managed-services/forge-squid/maintenance-status
#
# Env: ${FORGE_SQUID_ENV_FILE:-~/.config/forge-squid/forge-squid.env}
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY="$HERE/deploy/forge-squid"
# shellcheck source=scripts/fleet-rollout-step.sh
source "$HERE/scripts/fleet-rollout-step.sh"

SERVICE_ID="${FLEET_FORGE_SQUID_SERVICE_ID:-forge-squid}"
LOG_PATH="${FLEET_FORGE_SQUID_ROLLOUT_LOG:-$HOME/.local/state/forge-fleet/rollout-logs/${SERVICE_ID}.log}"
export FORGE_SQUID_ENV_FILE="${FORGE_SQUID_ENV_FILE:-$HOME/.config/forge-squid/forge-squid.env}"
if [[ ! -f "$FORGE_SQUID_ENV_FILE" && -f "$HOME/.config/forge-2b-poc/forge-2b.env" ]]; then
  export FORGE_SQUID_ENV_FILE="$HOME/.config/forge-2b-poc/forge-2b.env"
fi
export OPEN_WEBUI_NETWORK="${OPEN_WEBUI_NETWORK:-forge-open-webui_default}"
export FORGE_LLM_NETWORK="${FORGE_LLM_NETWORK:-forge-llm-control-plane_default}"
MODE_FILE="${FORGE_SQUID_DCE_MODE_FILE:-$HOME/.config/forge-squid/dce-mode}"
if [[ ! -f "$MODE_FILE" && -f "$HOME/.config/forge-2b-poc/dce-mode" ]]; then
  MODE_FILE="$HOME/.config/forge-2b-poc/dce-mode"
fi

compose() { docker compose -f "$DEPLOY/compose.yaml" "$@"; }

export DOCKER_BUILDKIT="${FORGE_SQUID_DOCKER_BUILDKIT:-${FLEET_DOCKER_BUILDKIT:-0}}"
export COMPOSE_DOCKER_CLI_BUILD="${COMPOSE_DOCKER_CLI_BUILD:-$DOCKER_BUILDKIT}"

if [[ "${1:-}" == "--down" ]]; then
  compose down
  exit 0
fi

if [[ -z "${FORGE_SQUID_DCE_MODE:-}" && -n "${FORGE_2B_DCE_MODE:-}" ]]; then
  FORGE_SQUID_DCE_MODE="$FORGE_2B_DCE_MODE"
fi
if [[ -z "${FORGE_SQUID_DCE_MODE:-}" && -f "$MODE_FILE" ]]; then
  FORGE_SQUID_DCE_MODE="$(tr -d '[:space:]' < "$MODE_FILE")"
fi
FORGE_SQUID_DCE_MODE="$(printf '%s' "${FORGE_SQUID_DCE_MODE:-off}" | tr '[:upper:]' '[:lower:]')"
case "$FORGE_SQUID_DCE_MODE" in
  off|shadow|on) ;;
  *) echo "FORGE_SQUID_DCE_MODE must be off|shadow|on (got '$FORGE_SQUID_DCE_MODE')" >&2; exit 2 ;;
esac
export FORGE_SQUID_DCE_MODE

fleet_rollout_begin "$SERVICE_ID" "$LOG_PATH"
fleet_rollout_step "prepare" "Checking env file, vendored sources and compose networks"
[[ -f "$FORGE_SQUID_ENV_FILE" ]] || { fleet_rollout_failed "prepare" "missing env file $FORGE_SQUID_ENV_FILE (copy forge-squid.env.example)"; exit 2; }
[[ -f "$DEPLOY/vendor/forge_squid/facade.py" ]] || { fleet_rollout_failed "prepare" "vendor/ not synced; run scripts/sync-forge-squid.sh and push"; exit 2; }
for net in "$OPEN_WEBUI_NETWORK" "$FORGE_LLM_NETWORK"; do
  docker network inspect "$net" >/dev/null 2>&1 || { fleet_rollout_failed "prepare" "network $net missing"; exit 2; }
done
echo "[forge-squid] sources: $(tr '\n' ';' < "$DEPLOY/vendor/SOURCES.txt")"
echo "[forge-squid] dce_mode=$FORGE_SQUID_DCE_MODE (vendored dce package: $([[ -d "$DEPLOY/vendor/forge_squid/dce" ]] && echo yes || echo no))"
if [[ "$FORGE_SQUID_DCE_MODE" != "off" && ! -d "$DEPLOY/vendor/forge_squid/dce" ]]; then
  fleet_rollout_failed "prepare" "dce_mode=$FORGE_SQUID_DCE_MODE requested but the vendored shim has no dce/ package"
  exit 2
fi

if [[ "${FORGE_SQUID_SKIP_BUILD:-0}" == "1" || "${FORGE_2B_SKIP_BUILD:-0}" == "1" ]]; then
  echo "[forge-squid] skip build: reusing image forge-squid:latest"
else
  fleet_rollout_step "build" "docker compose build --pull (forge-squid:latest)"
  compose build --pull forge-dcs
fi

fleet_rollout_step "restart" "docker compose up -d --force-recreate"
compose up -d --force-recreate --remove-orphans

fleet_rollout_step "health_check" "Waiting for forge-dcs and forge-squid health checks"
for _ in $(seq 1 30); do
  st_dcs="$(docker inspect -f '{{.State.Health.Status}}' forge-dcs 2>/dev/null || echo missing)"
  st_sq="$(docker inspect -f '{{.State.Health.Status}}' forge-squid 2>/dev/null || echo missing)"
  if [[ "$st_dcs" == healthy && "$st_sq" == healthy ]]; then
    echo "[forge-squid] healthy: forge-dcs=$st_dcs forge-squid=$st_sq"
    healthz="$(docker exec forge-squid python3 -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:9085/healthz',timeout=3).read().decode())")"
    echo "[forge-squid] healthz: $healthz"
    live_mode="$(printf '%s' "$healthz" | python3 -c "import json,sys;print(json.load(sys.stdin).get('dce_mode','<absent>'))" 2>/dev/null || echo '<unparsed>')"
    if [[ "$live_mode" != "$FORGE_SQUID_DCE_MODE" && ! ( "$live_mode" == "<absent>" && "$FORGE_SQUID_DCE_MODE" == "off" ) ]]; then
      fleet_rollout_failed "health_check" "container reports dce_mode=$live_mode, rollout asked for $FORGE_SQUID_DCE_MODE"
      exit 1
    fi
    fleet_rollout_step "finalize" "Recording dce_mode=$FORGE_SQUID_DCE_MODE"
    mkdir -p "$(dirname "$MODE_FILE")"
    printf '%s\n' "$FORGE_SQUID_DCE_MODE" > "$MODE_FILE"
    fleet_rollout_done
    exit 0
  fi
  sleep 3
done
echo "[forge-squid] not healthy after 90s: forge-dcs=$st_dcs forge-squid=$st_sq" >&2
docker logs --tail 40 forge-squid >&2 || true
fleet_rollout_failed "health_check" "not healthy after 90s: forge-dcs=$st_dcs forge-squid=$st_sq"
exit 1
