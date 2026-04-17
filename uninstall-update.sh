#!/usr/bin/env bash
# uninstall-update.sh — remove system Fleet unit (install-update.sh / systemd system instance).
# Defaults match install-update.sh: FLEET_DEST=/opt/forge-fleet, FLEET_DATA=/var/lib/forge-fleet.
#
# Flags:
#   --dry-run  — print only
#   --purge    — remove FLEET_DEST and FLEET_DATA trees (needs -y; paths must resolve under allowed prefixes)
#   -y, --yes  — non-interactive for --purge
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

FLEET_DEST="${FLEET_DEST:-/opt/forge-fleet}"
FLEET_DATA="${FLEET_DATA:-/var/lib/forge-fleet}"

die() { echo "uninstall-update.sh: $*" >&2; exit 1; }

SYS=()
[[ "$(id -u)" -eq 0 ]] || SYS=(sudo)

allowed_path() {
  local rp
  rp="$(realpath -m "$1" 2>/dev/null || true)"
  case "$rp" in
    /opt/forge-fleet|/opt/forge-fleet/*) return 0 ;;
    /var/lib/forge-fleet|/var/lib/forge-fleet/*) return 0 ;;
    *) return 1 ;;
  esac
}

echo "[uninstall-update] stopping system unit forge-fleet.service"

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run] systemctl disable --now forge-fleet.service"
else
  command -v systemctl >/dev/null 2>&1 && "${SYS[@]}" systemctl disable --now forge-fleet.service 2>/dev/null || true
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run] rm -f /etc/systemd/system/forge-fleet.service"
  echo "[dry-run] rm -rf /etc/systemd/system/forge-fleet.service.d"
else
  "${SYS[@]}" rm -f /etc/systemd/system/forge-fleet.service
  "${SYS[@]}" rm -rf /etc/systemd/system/forge-fleet.service.d
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run] systemctl daemon-reload"
else
  command -v systemctl >/dev/null 2>&1 && "${SYS[@]}" systemctl daemon-reload
fi

echo "[uninstall-update] removed /etc/systemd/system/forge-fleet.service"

if [[ "$PURGE" -eq 1 ]]; then
  allowed_path "$FLEET_DEST" || die "--purge: FLEET_DEST must resolve under /opt/forge-fleet (got $(realpath -m "$FLEET_DEST"))"
  allowed_path "$FLEET_DATA" || die "--purge: FLEET_DATA must resolve under /var/lib/forge-fleet (got $(realpath -m "$FLEET_DATA"))"

  if [[ "$YES" -eq 0 ]] && [[ "$DRY_RUN" -eq 0 ]] && [[ -t 0 ]]; then
    read -r -p "Delete $FLEET_DEST and $FLEET_DATA ? [y/N] " ans || true
    [[ "${ans:-}" =~ ^[Yy]$ ]] || die "aborted"
  elif [[ "$YES" -eq 0 ]] && [[ "$DRY_RUN" -eq 0 ]]; then
    die "--purge needs -y when stdin is not a tty"
  fi

  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] rm -rf \"$FLEET_DEST\" \"$FLEET_DATA\""
    echo "[dry-run] rm -f /etc/forge-fleet/forge-fleet.env; rmdir /etc/forge-fleet 2>/dev/null || true"
  else
    "${SYS[@]}" rm -rf "$FLEET_DEST" "$FLEET_DATA"
    "${SYS[@]}" rm -f /etc/forge-fleet/forge-fleet.env
    "${SYS[@]}" rmdir /etc/forge-fleet 2>/dev/null || true
  fi
  echo "[uninstall-update] purge complete"
else
  echo "[uninstall-update] left FLEET_DEST and FLEET_DATA on disk (use --purge -y to remove)"
fi
