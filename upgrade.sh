#!/usr/bin/env bash
# upgrade.sh — pull latest forge-fleet from git, then refresh the local install
# (user systemd --user OR system /opt) based on which unit file is present.
#
# Run from anywhere:
#   /path/to/forge-fleet/upgrade.sh
# Or:
#   cd /path/to/forge-fleet && ./upgrade.sh
#
# Options:
#   --user          force user install (update-user.sh), ignore system detection
#   --system        force system install (sudo install-update.sh)
#   --no-pull       skip git pull and submodule update (only re-run install step)
#   --pull-merge    use plain "git pull" instead of "git pull --ff-only"
#   -h, --help
#
# If both ~/.config/systemd/user/forge-fleet.service and
# /etc/systemd/system/forge-fleet.service exist, pass --user or --system.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

FORCE_USER=0
FORCE_SYSTEM=0
NO_PULL=0
FF_ONLY=1

usage() {
  cat >&2 <<'EOF'
upgrade.sh — git pull + submodule update, then refresh the local Fleet install.

  User install:   ~/.config/systemd/user/forge-fleet.service → update-user.sh
  System install: /etc/systemd/system/forge-fleet.service → sudo install-update.sh

Run:  /path/to/forge-fleet/upgrade.sh   or   cd /path/to/forge-fleet && ./upgrade.sh

Options:
  --user          force user install
  --system        force system install (sudo)
  --no-pull       only re-run install step (no git pull)
  --pull-merge    use "git pull" instead of "git pull --ff-only"
  -h, --help

If both user and system unit files exist, pass --user or --system.
EOF
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user) FORCE_USER=1; shift ;;
    --system) FORCE_SYSTEM=1; shift ;;
    --no-pull) NO_PULL=1; shift ;;
    --pull-merge) FF_ONLY=0; shift ;;
    -h|--help) usage 0 ;;
    *)
      echo "upgrade.sh: unknown option: $1" >&2
      usage 2
      ;;
  esac
done

if [[ "$FORCE_USER" -eq 1 ]] && [[ "$FORCE_SYSTEM" -eq 1 ]]; then
  echo "upgrade.sh: pass only one of --user or --system" >&2
  exit 2
fi

[[ -d "$ROOT/fleet_server" ]] || { echo "upgrade.sh: not a forge-fleet repo (missing fleet_server/): $ROOT" >&2; exit 1; }

_USER_UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/forge-fleet.service"
_SYSTEM_UNIT="/etc/systemd/system/forge-fleet.service"

has_user() { [[ -f "$_USER_UNIT" ]]; }
has_system() { [[ -f "$_SYSTEM_UNIT" ]]; }

choose_mode() {
  if [[ "$FORCE_USER" -eq 1 ]]; then
    echo user
    return
  fi
  if [[ "$FORCE_SYSTEM" -eq 1 ]]; then
    echo system
    return
  fi
  local u s
  u=0; s=0
  has_user && u=1
  has_system && s=1
  if [[ "$u" -eq 1 ]] && [[ "$s" -eq 1 ]]; then
    echo "upgrade.sh: both user and system forge-fleet.service units exist." >&2
    echo "  $_USER_UNIT" >&2
    echo "  $_SYSTEM_UNIT" >&2
    echo "Re-run with --user or --system." >&2
    exit 1
  fi
  if [[ "$u" -eq 1 ]]; then
    echo user
    return
  fi
  if [[ "$s" -eq 1 ]]; then
    echo system
    return
  fi
  echo "upgrade.sh: no forge-fleet systemd unit found." >&2
  echo "  User install:  env FLEET_SRC=\"\$PWD\" ./install-user.sh" >&2
  echo "  System install: sudo env FLEET_SRC=\"\$PWD\" ./install-update.sh" >&2
  echo "  First-time clone: ./git-install.sh" >&2
  exit 1
}

MODE="$(choose_mode)"

if [[ "$NO_PULL" -eq 0 ]]; then
  echo "[upgrade] git pull ($([[ "$FF_ONLY" -eq 1 ]] && echo --ff-only || echo merge allowed))…"
  if [[ "$FF_ONLY" -eq 1 ]]; then
    git pull --ff-only
  else
    git pull
  fi
  echo "[upgrade] git submodule update…"
  git submodule update --init --recursive
else
  echo "[upgrade] skipped git pull (--no-pull)"
fi

export FLEET_SRC="$ROOT"

case "$MODE" in
  user)
    echo "[upgrade] refreshing user install (update-user.sh)…"
    exec "$ROOT/update-user.sh"
    ;;
  system)
    echo "[upgrade] refreshing system install (sudo install-update.sh)…"
    exec sudo env FLEET_SRC="$ROOT" "$ROOT/install-update.sh"
    ;;
  *)
    echo "upgrade.sh: internal error (mode=$MODE)" >&2
    exit 1
    ;;
esac
