#!/usr/bin/env bash
# install-update.sh — copy a development checkout into the production tree used
# by systemd, refresh the unit, and optionally restart the daemon.
#
# Port convention (do not collide dev and prod):
#   Production (this script + systemd): 18765
#   Development (./run-dev.sh from checkout): 18766 + separate SQLite dir
#
# Typical:  cd ~/Code/forge-fleet && git pull && git submodule update --init --recursive && sudo ./install-update.sh
# Same script for updates. Remove system install: sudo ./uninstall-update.sh  (see also ./update-system.sh)
# Fresh clone on a new host: ./git-install.sh  (submodules + this script); see docs/GIT-INSTALL.md
#
# Env (optional):
#   FLEET_SRC    — dev checkout (default: dir containing this script if it has fleet_server/, else $HOME/Code/forge-fleet)
#   FLEET_DEST   — production install root (default: /opt/forge-fleet), never your live checkout
#   FLEET_DATA   — production --data-dir (default: /var/lib/forge-fleet); holds fleet.sqlite plus etc/containers + etc/services
#   FLEET_PYTHON — Python for systemd ExecStart (default: /usr/bin/python3)
#   FLEET_PORT   — production listen port (default: 18765)
#
# Flags:
#   --no-systemd — only rsync; do not write unit or touch systemd
#   --no-restart — write unit / daemon-reload but do not restart the service
#   --dry-run    — rsync -n only (no writes; systemd steps skipped)
#   -h, --help

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_SYSTEMD=1
RESTART_SERVICE=1
DRY_RUN=0
POS_SRC=""

usage() {
  sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-systemd) INSTALL_SYSTEMD=0; RESTART_SERVICE=0; shift ;;
    --no-restart) RESTART_SERVICE=0; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage 0 ;;
    --) shift; break ;;
    -*)
      echo "unknown option: $1" >&2
      usage 2
      ;;
    *)
      if [[ -n "$POS_SRC" ]]; then
        echo "extra argument: $1" >&2
        usage 2
      fi
      POS_SRC="$1"
      shift
      ;;
  esac
done

FLEET_DEST="${FLEET_DEST:-/opt/forge-fleet}"
FLEET_DATA="${FLEET_DATA:-/var/lib/forge-fleet}"
FLEET_PYTHON="${FLEET_PYTHON:-/usr/bin/python3}"
FLEET_PORT="${FLEET_PORT:-18765}"

if [[ -n "$POS_SRC" ]]; then
  FLEET_SRC="$POS_SRC"
elif [[ -n "${FLEET_SRC:-}" ]]; then
  :
elif [[ -d "$SCRIPT_DIR/fleet_server" ]]; then
  FLEET_SRC="$SCRIPT_DIR"
else
  FLEET_SRC="${HOME}/Code/forge-fleet"
fi

FLEET_SRC="$(cd "$FLEET_SRC" && pwd)"

die() { echo "install-update.sh: $*" >&2; exit 1; }

[[ -d "$FLEET_SRC/fleet_server" ]] || die "missing fleet_server in FLEET_SRC=$FLEET_SRC"
[[ -d "$FLEET_SRC/kitchensink" ]] || die "missing kitchensink/ — run: git -C \"$FLEET_SRC\" submodule update --init --recursive"

command -v rsync >/dev/null || die "rsync not found (apt install rsync)"

SUDO=()
if [[ "$(id -u)" -ne 0 ]]; then
  parent="$(dirname "$FLEET_DEST")"
  if [[ ! -d "$FLEET_DEST" ]] && [[ ! -w "$parent" ]]; then
    SUDO=(sudo)
  elif [[ -d "$FLEET_DEST" ]] && [[ ! -w "$FLEET_DEST" ]]; then
    SUDO=(sudo)
  fi
fi

"${SUDO[@]}" mkdir -p "$FLEET_DEST"
FLEET_DEST="$(cd "$FLEET_DEST" && pwd)"

[[ "$FLEET_SRC" != "$FLEET_DEST" ]] || die "FLEET_SRC and FLEET_DEST are the same path (production must not be your checkout)"

RSYNC=(rsync -a)
if [[ "$DRY_RUN" -eq 1 ]]; then
  RSYNC+=(-n)
fi

"${SUDO[@]}" "${RSYNC[@]}" \
  --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '*.egg-info/' \
  --exclude '.fleet-data/' \
  --exclude 'blueprints/' \
  "$FLEET_SRC/" "$FLEET_DEST/"

echo "[install-update] synced $FLEET_SRC -> $FLEET_DEST"

if [[ "$INSTALL_SYSTEMD" -eq 1 ]] && [[ "$DRY_RUN" -eq 0 ]]; then
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "[install-update] skip systemd (no systemctl)"
  else
    SYS_SUDO=()
    [[ "$(id -u)" -eq 0 ]] || SYS_SUDO=(sudo)

    UNIT_SRC="$FLEET_SRC/systemd/forge-fleet.service"
    [[ -f "$UNIT_SRC" ]] || die "missing $UNIT_SRC"

    esc_py="${FLEET_PYTHON//\\/\\\\}"
    esc_py="${esc_py//|/\\|}"
    esc_dest="${FLEET_DEST//\\/\\\\}"
    esc_dest="${esc_dest//|/\\|}"
    esc_data="${FLEET_DATA//\\/\\\\}"
    esc_data="${esc_data//|/\\|}"

    UFILE="$(mktemp "${TMPDIR:-/tmp}/forge-fleet.service.XXXXXX")"
    sed \
      -e "s|^WorkingDirectory=.*|WorkingDirectory=$esc_dest|" \
      -e "s|^ExecStart=.*|ExecStart=$esc_py -m fleet_server --host 0.0.0.0 --port $FLEET_PORT --data-dir $esc_data|" \
      "$UNIT_SRC" >"$UFILE"

    "${SYS_SUDO[@]}" install -d /etc/forge-fleet
    if [[ ! -f /etc/forge-fleet/forge-fleet.env ]]; then
      if [[ -f "$FLEET_SRC/systemd/environment.example" ]]; then
        "${SYS_SUDO[@]}" install -m0600 "$FLEET_SRC/systemd/environment.example" /etc/forge-fleet/forge-fleet.env
        echo "[install-update] created /etc/forge-fleet/forge-fleet.env — set FLEET_BEARER_TOKEN for non-loopback"
      fi
    fi

    HELPER="$FLEET_SRC/scripts/set-fleet-git-root-in-env.sh"
    if [[ -f "$HELPER" ]]; then
      "${SYS_SUDO[@]}" bash "$HELPER" /etc/forge-fleet/forge-fleet.env "$FLEET_SRC"
    fi

    "${SYS_SUDO[@]}" install -m0644 "$UFILE" /etc/systemd/system/forge-fleet.service
    rm -f "$UFILE"

    UTELEM="$(mktemp "${TMPDIR:-/tmp}/forge-fleet-telemetry.service.XXXXXX")"
    {
      echo "[Unit]"
      echo "Description=Forge Fleet — SQLite telemetry sample (one-shot)"
      echo "After=network.target"
      echo ""
      echo "[Service]"
      echo "Type=oneshot"
      echo "SyslogIdentifier=forge-fleet-telemetry"
      echo "Environment=PYTHONUNBUFFERED=1"
      echo "User=forge-fleet"
      echo "Group=forge-fleet"
      echo "SupplementaryGroups=docker"
      echo "WorkingDirectory=$esc_dest"
      echo "EnvironmentFile=-/etc/forge-fleet/forge-fleet.env"
      echo "ExecStart=$esc_py -m fleet_server.telemetry_sampler --data-dir $esc_data"
    } >"$UTELEM"
    "${SYS_SUDO[@]}" install -m0644 "$UTELEM" /etc/systemd/system/forge-fleet-telemetry.service
    rm -f "$UTELEM"

    UTTIMER="$(mktemp "${TMPDIR:-/tmp}/forge-fleet-telemetry.timer.XXXXXX")"
    {
      echo "[Unit]"
      echo "Description=Timer — Forge Fleet telemetry to SQLite (works when HTTP is stopped)"
      echo ""
      echo "[Timer]"
      echo "OnBootSec=45s"
      echo "OnUnitActiveSec=1min"
      echo "AccuracySec=1min"
      echo "Unit=forge-fleet-telemetry.service"
      echo ""
      echo "[Install]"
      echo "WantedBy=timers.target"
    } >"$UTTIMER"
    "${SYS_SUDO[@]}" install -m0644 "$UTTIMER" /etc/systemd/system/forge-fleet-telemetry.timer
    rm -f "$UTTIMER"

    "${SYS_SUDO[@]}" systemctl daemon-reload
    echo "[install-update] systemd unit -> /etc/systemd/system/forge-fleet.service (port $FLEET_PORT)"
    echo "[install-update] telemetry timer -> /etc/systemd/system/forge-fleet-telemetry.timer"

    if "${SYS_SUDO[@]}" systemctl enable --now forge-fleet-telemetry.timer 2>/dev/null; then
      echo "[install-update] enabled forge-fleet-telemetry.timer (SQLite telemetry when HTTP is stopped)"
    else
      echo "[install-update] warning: could not enable forge-fleet-telemetry.timer" >&2
    fi

    if [[ "$RESTART_SERVICE" -eq 1 ]]; then
      if "${SYS_SUDO[@]}" systemctl restart forge-fleet.service; then
        echo "[install-update] restarted forge-fleet.service"
      else
        echo "[install-update] restart failed (first time? run: sudo systemctl enable --now forge-fleet.service)" >&2
      fi
    else
      echo "[install-update] skipped restart (--no-restart); apply with: sudo systemctl restart forge-fleet.service"
    fi
  fi
elif [[ "$INSTALL_SYSTEMD" -eq 1 ]] && [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[install-update] dry-run: skipped systemd unit write and restart"
fi
