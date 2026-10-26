#!/usr/bin/env bash
# Upgrade Fleet on this host, every direct remote peer, and each hub's remote peers (one hop).
#
# Uses bearer tokens from FLEET_DATA_DIR/etc/remote-peers.json for hub APIs only (never printed).
#
# Usage:
#   ./scripts/upgrade-mesh-fleets.sh
#   FLEET_LOCAL_URL=http://127.0.0.1:18766 FLEET_LOCAL_BEARER=... ./scripts/upgrade-mesh-fleets.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export FLEET_DATA_DIR="${FLEET_DATA_DIR:-${HOME}/.local/state/forge-fleet}"
export FLEET_LOCAL_URL="${FLEET_LOCAL_URL:-http://127.0.0.1:18766}"

exec python3 "$ROOT/scripts/upgrade_mesh_fleets.py"
