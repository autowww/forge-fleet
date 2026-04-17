#!/usr/bin/env bash
# update-user.sh — same as install-user.sh: rsync checkout -> ~/.local/share/forge-fleet,
# refresh systemd --user unit, restart. Use after git pull.
#
# Env/flags: same as install-user.sh (FLEET_SRC, FLEET_USER_DEST, --no-restart, --dry-run, …).

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "[update-user] refreshing user install (see install-user.sh for options)"
exec "$ROOT/install-user.sh" "$@"
