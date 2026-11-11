#!/usr/bin/env bash
# Build + (re)start the forge-2b PoC stack on a Fleet host from the git checkout.
#
#   ~/forge-fleet/scripts/rollout-forge-2b-poc.sh            # build, up -d, wait healthy
#   ~/forge-fleet/scripts/rollout-forge-2b-poc.sh --down     # compose down (volumes kept)
#
# Also runs through the generic Fleet rollout API (registry id `forge-2b-poc`):
#   POST /v1/managed-services/forge-2b-poc/rollout  {"forge_2b_dce_mode": "off|shadow|on", "forge_2b_skip_build": "1"}
#   GET  /v1/managed-services/forge-2b-poc/maintenance-status
#
# Env file: ${FORGE_2B_ENV_FILE:-~/.config/forge-2b-poc/forge-2b.env} (see deploy/forge-2b-poc/forge-2b.env.example).
# DCE mode: FORGE_2B_DCE_MODE (off|shadow|on). When unset, the last mode chosen by a rollout is reused
# (${FORGE_2B_DCE_MODE_FILE:-~/.config/forge-2b-poc/dce-mode}); default off. Every rollout records the mode it applied.
# Requires the Open WebUI compose network (default forge-open-webui_default) to exist.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY="$HERE/deploy/forge-2b-poc"
# shellcheck source=scripts/fleet-rollout-step.sh
source "$HERE/scripts/fleet-rollout-step.sh"

SERVICE_ID="${FLEET_FORGE_2B_SERVICE_ID:-forge-2b-poc}"
LOG_PATH="${FLEET_FORGE_2B_ROLLOUT_LOG:-$HOME/.local/state/forge-fleet/rollout-logs/${SERVICE_ID}.log}"
export FORGE_2B_ENV_FILE="${FORGE_2B_ENV_FILE:-$HOME/.config/forge-2b-poc/forge-2b.env}"
export OPEN_WEBUI_NETWORK="${OPEN_WEBUI_NETWORK:-forge-open-webui_default}"
export FORGE_LLM_NETWORK="${FORGE_LLM_NETWORK:-forge-llm-control-plane_default}"
MODE_FILE="${FORGE_2B_DCE_MODE_FILE:-$HOME/.config/forge-2b-poc/dce-mode}"

compose() { docker compose -f "$DEPLOY/compose.yaml" "$@"; }

# Fleet hosts: ~/.docker/buildx may be root-owned while rollouts run as the git install user.
export DOCKER_BUILDKIT="${FORGE_2B_DOCKER_BUILDKIT:-${FLEET_DOCKER_BUILDKIT:-0}}"
export COMPOSE_DOCKER_CLI_BUILD="${COMPOSE_DOCKER_CLI_BUILD:-$DOCKER_BUILDKIT}"

if [[ "${1:-}" == "--down" ]]; then
  compose down
  exit 0
fi

# --- DCE mode: explicit > sticky file > off; anything unknown is refused before touching containers ---------------------
if [[ -z "${FORGE_2B_DCE_MODE:-}" && -f "$MODE_FILE" ]]; then
  FORGE_2B_DCE_MODE="$(tr -d '[:space:]' < "$MODE_FILE")"
fi
FORGE_2B_DCE_MODE="$(printf '%s' "${FORGE_2B_DCE_MODE:-off}" | tr '[:upper:]' '[:lower:]')"
case "$FORGE_2B_DCE_MODE" in
  off|shadow|on) ;;
  *) echo "FORGE_2B_DCE_MODE must be off|shadow|on (got '$FORGE_2B_DCE_MODE')" >&2; exit 2 ;;
esac
export FORGE_2B_DCE_MODE

fleet_rollout_begin "$SERVICE_ID" "$LOG_PATH"
fleet_rollout_step "prepare" "Checking env file, vendored sources and compose networks"
[[ -f "$FORGE_2B_ENV_FILE" ]] || { fleet_rollout_failed "prepare" "missing env file $FORGE_2B_ENV_FILE (copy forge-2b.env.example)"; exit 2; }
[[ -f "$DEPLOY/vendor/forge_2b/facade.py" ]] || { fleet_rollout_failed "prepare" "vendor/ not synced; run scripts/sync-forge-2b-poc.sh and push"; exit 2; }
for net in "$OPEN_WEBUI_NETWORK" "$FORGE_LLM_NETWORK"; do
  docker network inspect "$net" >/dev/null 2>&1 || { fleet_rollout_failed "prepare" "network $net missing"; exit 2; }
done
echo "[forge-2b-poc] sources: $(tr '\n' ';' < "$DEPLOY/vendor/SOURCES.txt")"
echo "[forge-2b-poc] dce_mode=$FORGE_2B_DCE_MODE (vendored dce package: $([[ -d "$DEPLOY/vendor/forge_2b/dce" ]] && echo yes || echo no))"
if [[ "$FORGE_2B_DCE_MODE" != "off" && ! -d "$DEPLOY/vendor/forge_2b/dce" ]]; then
  fleet_rollout_failed "prepare" "dce_mode=$FORGE_2B_DCE_MODE requested but the vendored shim has no dce/ package"
  exit 2
fi

if [[ "${FORGE_2B_SKIP_BUILD:-0}" == "1" ]]; then
  echo "[forge-2b-poc] FORGE_2B_SKIP_BUILD=1: reusing image forge-2b-poc:latest"
else
  fleet_rollout_step "build" "docker compose build --pull (forge-2b-poc:latest)"
  compose build --pull forge-dcs
fi

fleet_rollout_step "restart" "docker compose up -d --force-recreate"
compose up -d --force-recreate --remove-orphans

fleet_rollout_step "health_check" "Waiting for forge-dcs and forge-2b health checks"
for _ in $(seq 1 30); do
  st_dcs="$(docker inspect -f '{{.State.Health.Status}}' forge-dcs 2>/dev/null || echo missing)"
  st_2b="$(docker inspect -f '{{.State.Health.Status}}' forge-2b 2>/dev/null || echo missing)"
  if [[ "$st_dcs" == healthy && "$st_2b" == healthy ]]; then
    echo "[forge-2b-poc] healthy: forge-dcs=$st_dcs forge-2b=$st_2b"
    healthz="$(docker exec forge-2b python3 -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:9085/healthz',timeout=3).read().decode())")"
    echo "[forge-2b-poc] healthz: $healthz"
    live_mode="$(printf '%s' "$healthz" | python3 -c "import json,sys;print(json.load(sys.stdin).get('dce_mode','<absent>'))" 2>/dev/null || echo '<unparsed>')"
    if [[ "$live_mode" != "$FORGE_2B_DCE_MODE" && ! ( "$live_mode" == "<absent>" && "$FORGE_2B_DCE_MODE" == "off" ) ]]; then
      fleet_rollout_failed "health_check" "container reports dce_mode=$live_mode, rollout asked for $FORGE_2B_DCE_MODE"
      exit 1
    fi
    fleet_rollout_step "finalize" "Recording dce_mode=$FORGE_2B_DCE_MODE"
    mkdir -p "$(dirname "$MODE_FILE")"
    printf '%s\n' "$FORGE_2B_DCE_MODE" > "$MODE_FILE"
    fleet_rollout_done
    exit 0
  fi
  sleep 3
done
echo "[forge-2b-poc] not healthy after 90s: forge-dcs=$st_dcs forge-2b=$st_2b" >&2
docker logs --tail 40 forge-2b >&2 || true
fleet_rollout_failed "health_check" "not healthy after 90s: forge-dcs=$st_dcs forge-2b=$st_2b"
exit 1
