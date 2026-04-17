#!/usr/bin/env bash
# run-dev.sh — run Fleet from this checkout on port 18766 with a dev-only SQLite dir
# so production (systemd on 18765 under /opt/forge-fleet) is unaffected.
#
# Env (optional):
#   FLEET_DEV_PORT   — default 18766
#   FLEET_DEV_DATA   — default $XDG_STATE_HOME/forge-fleet-dev or ~/.local/state/forge-fleet-dev
#   FLEET_DEV_HOST   — default 127.0.0.1
#   FLEET_BEARER_TOKEN — optional; passed through to the server

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

FLEET_DEV_PORT="${FLEET_DEV_PORT:-18766}"
FLEET_DEV_HOST="${FLEET_DEV_HOST:-127.0.0.1}"
if [[ -n "${FLEET_DEV_DATA:-}" ]]; then
  :
elif [[ -n "${XDG_STATE_HOME:-}" ]]; then
  FLEET_DEV_DATA="${XDG_STATE_HOME}/forge-fleet-dev"
else
  FLEET_DEV_DATA="${HOME}/.local/state/forge-fleet-dev"
fi

[[ -d fleet_server ]] || { echo "run-dev.sh: run from forge-fleet repo root" >&2; exit 1; }
[[ -d kitchensink ]] || { echo "run-dev.sh: missing kitchensink/ (git submodule update --init --recursive)" >&2; exit 1; }

echo "[run-dev] http://${FLEET_DEV_HOST}:${FLEET_DEV_PORT}/  data-dir=$FLEET_DEV_DATA (production uses 18765 + /var/lib/forge-fleet via install-update.sh)"
exec python3 -m fleet_server --host "$FLEET_DEV_HOST" --port "$FLEET_DEV_PORT" --data-dir "$FLEET_DEV_DATA"
