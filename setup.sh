#!/usr/bin/env bash
# setup.sh — user-level Fleet: create XDG dirs, sync from this repo, install systemd --user unit, start service.
# Same flags/env as install-user.sh (--no-systemd, --no-restart, --dry-run, FLEET_USER_DEST, …).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

FLEET_USER_DEST="${FLEET_USER_DEST:-${HOME}/.local/share/forge-fleet}"
FLEET_USER_DATA="${FLEET_USER_DATA:-${HOME}/.local/state/forge-fleet}"
CFG="${XDG_CONFIG_HOME:-${HOME}/.config}"
FLEET_USER_PORT="${FLEET_USER_PORT:-18766}"
FLEET_USER_HOST="${FLEET_USER_HOST:-127.0.0.1}"

echo "[setup] install tree:  $FLEET_USER_DEST"
echo "[setup] data (SQLite): $FLEET_USER_DATA"
echo "[setup] user units:    $CFG/systemd/user/"
echo "[setup] optional env:  $CFG/forge-fleet/forge-fleet.env"
echo "[setup] listen:        $FLEET_USER_HOST:$FLEET_USER_PORT"
echo "[setup] later:          ./update-user.sh   | remove: ./uninstall-user.sh [--purge -y]"

mkdir -p \
  "$FLEET_USER_DEST" \
  "$FLEET_USER_DATA" \
  "$CFG/systemd/user" \
  "$CFG/forge-fleet"

if [[ ! -x "$ROOT/install-user.sh" ]]; then
  chmod +x "$ROOT/install-user.sh" || true
fi

exec "$ROOT/install-user.sh" "$@"
