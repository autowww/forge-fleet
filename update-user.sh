#!/usr/bin/env bash
# update-user.sh — same as install-user.sh: rsync checkout -> ~/.local/share/forge-fleet,
# refresh systemd --user unit, restart. Use after git pull.
#
# Env/flags: same as install-user.sh (FLEET_SRC, FLEET_USER_DEST, --no-restart, --dry-run, …).

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_pp="$ROOT/pyproject.toml"
if [ -f "$_pp" ]; then
  # Single-line project version from TOML (no extra deps).
  FLEET_VER="$(grep -E '^[[:space:]]*version[[:space:]]*=' "$_pp" | head -1 | sed -E 's/^[[:space:]]*version[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/')"
  echo "[update-user] forge-fleet version (pyproject.toml): ${FLEET_VER:-unknown}"
else
  echo "[update-user] forge-fleet version: unknown (pyproject.toml missing under $ROOT)"
fi
echo "[update-user] refreshing user install (see install-user.sh for options)"
exec "$ROOT/install-user.sh" "$@"
