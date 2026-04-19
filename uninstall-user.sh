#!/usr/bin/env bash
# uninstall-user.sh — remove systemd --user Fleet unit; optionally purge XDG dirs (same defaults as setup.sh).
#
# Defaults (override with env, must match what you installed):
#   FLEET_USER_DEST  — default $HOME/.local/share/forge-fleet
#   FLEET_USER_DATA  — default $HOME/.local/state/forge-fleet
#   XDG_CONFIG_HOME  — default $HOME/.config
#
# Flags:
#   --dry-run   — print actions only
#   --purge     — also remove install tree, state dir, and forge-fleet.env (needs -y or tty confirm)
#   -y, --yes   — non-interactive confirm for --purge
#   -h, --help

set -euo pipefail

DRY_RUN=0
PURGE=0
YES=0

usage() {
  sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --purge) PURGE=1; shift ;;
    -y|--yes) YES=1; shift ;;
    -h|--help) usage 0 ;;
    -*)
      echo "unknown option: $1" >&2
      usage 2
      ;;
    *)
      echo "unexpected argument: $1" >&2
      usage 2
      ;;
  esac
done

FLEET_USER_DEST="${FLEET_USER_DEST:-${HOME}/.local/share/forge-fleet}"
FLEET_USER_DATA="${FLEET_USER_DATA:-${HOME}/.local/state/forge-fleet}"
CFG="${XDG_CONFIG_HOME:-${HOME}/.config}"
UNIT_DIR="${CFG}/systemd/user"
ENV_DIR="${CFG}/forge-fleet"
UNIT="${UNIT_DIR}/forge-fleet.service"
TTIMER="${UNIT_DIR}/forge-fleet-telemetry.timer"
TSVC="${UNIT_DIR}/forge-fleet-telemetry.service"
DROPIN="${UNIT_DIR}/forge-fleet.service.d"

die() { echo "uninstall-user.sh: $*" >&2; exit 1; }

under_home() {
  local rp
  rp="$(realpath -m "$1" 2>/dev/null || true)"
  [[ -n "$rp" ]] || return 1
  case "$rp" in
    "${HOME}"/*) return 0 ;;
    *) return 1 ;;
  esac
}

echo "[uninstall-user] unit: $UNIT"
echo "[uninstall-user] install tree: $FLEET_USER_DEST"
echo "[uninstall-user] data dir: $FLEET_USER_DATA"
echo "[uninstall-user] env file: $ENV_DIR/forge-fleet.env"

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run] systemctl --user disable --now forge-fleet-telemetry.timer"
  echo "[dry-run] systemctl --user disable --now forge-fleet-telemetry.service"
  echo "[dry-run] systemctl --user disable --now forge-fleet.service"
else
  command -v systemctl >/dev/null 2>&1 && systemctl --user disable --now forge-fleet-telemetry.timer 2>/dev/null || true
  command -v systemctl >/dev/null 2>&1 && systemctl --user disable --now forge-fleet-telemetry.service 2>/dev/null || true
  command -v systemctl >/dev/null 2>&1 && systemctl --user disable --now forge-fleet.service 2>/dev/null || true
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run] rm -f \"$UNIT\" \"$TSVC\" \"$TTIMER\""
  echo "[dry-run] rm -rf \"$DROPIN\""
else
  rm -f "$UNIT" "$TSVC" "$TTIMER"
  rm -rf "$DROPIN"
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run] systemctl --user daemon-reload"
else
  command -v systemctl >/dev/null 2>&1 && systemctl --user daemon-reload
fi

echo "[uninstall-user] removed user unit (service stopped if it was running)"

if [[ "$PURGE" -eq 1 ]]; then
  under_home "$FLEET_USER_DEST" || die "--purge: FLEET_USER_DEST must resolve under \$HOME (got $(realpath -m "$FLEET_USER_DEST"))"
  under_home "$FLEET_USER_DATA" || die "--purge: FLEET_USER_DATA must resolve under \$HOME (got $(realpath -m "$FLEET_USER_DATA"))"
  under_home "$ENV_DIR" || die "--purge: env dir must resolve under \$HOME"

  if [[ "$YES" -eq 0 ]] && [[ "$DRY_RUN" -eq 0 ]] && [[ -t 0 ]]; then
    read -r -p "Delete install tree, SQLite state, and env file? [y/N] " ans || true
    [[ "${ans:-}" =~ ^[Yy]$ ]] || die "aborted"
  elif [[ "$YES" -eq 0 ]] && [[ "$DRY_RUN" -eq 0 ]]; then
    die "--purge needs -y when stdin is not a tty"
  fi

  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] rm -rf \"$FLEET_USER_DEST\" \"$FLEET_USER_DATA\""
    echo "[dry-run] rm -f \"$ENV_DIR/forge-fleet.env\"; rmdir \"$ENV_DIR\" 2>/dev/null || true"
  else
    rm -rf "$FLEET_USER_DEST" "$FLEET_USER_DATA"
    rm -f "$ENV_DIR/forge-fleet.env"
    rmdir "$ENV_DIR" 2>/dev/null || true
  fi
  echo "[uninstall-user] purge complete"
else
  echo "[uninstall-user] data left on disk (use --purge -y to remove trees + env)"
fi
