#!/usr/bin/env bash
# install-user.sh — install Fleet under your home directory + systemd --user (no sudo).
# First-time flow: ./setup.sh  |  Later: ./update-user.sh  |  Remove: ./uninstall-user.sh
#
# Defaults (override with env):
#   FLEET_SRC          — checkout (same rules as install-update.sh)
#   FLEET_USER_DEST    — copy target (default: $HOME/.local/share/forge-fleet)
#   FLEET_USER_DATA    — SQLite dir (default: $HOME/.local/state/forge-fleet)
#                      — Fleet also writes ``etc/containers/types.json`` (versioned: categories + types) and
#                        ``etc/services/*.json`` here (same as --data-dir in the unit; see GET /v1/container-types).
#   FLEET_USER_HOST    — bind (default: 127.0.0.1)
#   FLEET_USER_PORT    — default 18766 (avoids clash with system prod on 18765)
#   FLEET_PYTHON       — interpreter (default: /usr/bin/python3)
#
# Boot without login session:  loginctl enable-linger "$USER"  (once, may prompt for polkit)
#
# SQLite telemetry when HTTP is down: forge-fleet-telemetry.timer (see systemd/environment.example).
#
# Flags: --no-systemd  --no-restart  --dry-run  -h/--help

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

FLEET_USER_DEST="${FLEET_USER_DEST:-${HOME}/.local/share/forge-fleet}"
FLEET_USER_DATA="${FLEET_USER_DATA:-${HOME}/.local/state/forge-fleet}"
FLEET_USER_HOST="${FLEET_USER_HOST:-127.0.0.1}"
FLEET_USER_PORT="${FLEET_USER_PORT:-18766}"
FLEET_PYTHON="${FLEET_PYTHON:-/usr/bin/python3}"

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
FLEET_DEST="$(mkdir -p "$FLEET_USER_DEST" && cd "$FLEET_USER_DEST" && pwd)"
FLEET_DATA="$(mkdir -p "$FLEET_USER_DATA" && cd "$FLEET_USER_DATA" && pwd)"

die() { echo "install-user.sh: $*" >&2; exit 1; }

[[ -d "$FLEET_SRC/fleet_server" ]] || die "missing fleet_server in FLEET_SRC=$FLEET_SRC"
[[ -d "$FLEET_SRC/kitchensink" ]] || die "missing kitchensink/ — git -C \"$FLEET_SRC\" submodule update --init --recursive"

command -v rsync >/dev/null || die "rsync not found (apt install rsync)"

[[ "$FLEET_SRC" != "$FLEET_DEST" ]] || die "FLEET_SRC and install destination are the same path"

RSYNC=(rsync -a)
if [[ "$DRY_RUN" -eq 1 ]]; then
  RSYNC+=(-n)
fi

"${RSYNC[@]}" \
  --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '*.egg-info/' \
  --exclude '.fleet-data/' \
  --exclude 'blueprints/' \
  "$FLEET_SRC/" "$FLEET_DEST/"

echo "[install-user] synced $FLEET_SRC -> $FLEET_DEST"

if [[ "$INSTALL_SYSTEMD" -eq 1 ]] && [[ "$DRY_RUN" -eq 0 ]]; then
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "[install-user] skip systemd (no systemctl)"
  else
    UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    ENV_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/forge-fleet"
    mkdir -p "$UNIT_DIR" "$ENV_DIR"

    if [[ ! -f "$ENV_DIR/forge-fleet.env" ]] && [[ -f "$FLEET_SRC/systemd/environment.example" ]]; then
      install -m0600 "$FLEET_SRC/systemd/environment.example" "$ENV_DIR/forge-fleet.env"
      echo "[install-user] created $ENV_DIR/forge-fleet.env (optional FLEET_BEARER_TOKEN on loopback)"
    fi

    esc_py="${FLEET_PYTHON//\\/\\\\}"
    esc_py="${esc_py//|/\\|}"
    esc_dest="${FLEET_DEST//\\/\\\\}"
    esc_dest="${esc_dest//|/\\|}"
    esc_data="${FLEET_DATA//\\/\\\\}"
    esc_data="${esc_data//|/\\|}"
    esc_host="${FLEET_USER_HOST//\\/\\\\}"
    esc_host="${esc_host//|/\\|}"

    UFILE="$(mktemp "${TMPDIR:-/tmp}/forge-fleet-user.service.XXXXXX")"
    {
      echo "[Unit]"
      echo "Description=Forge Fleet (user) — Docker argv HTTP orchestrator"
      echo "After=network-online.target docker.service"
      echo "Wants=network-online.target docker.service"
      echo ""
      echo "[Service]"
      echo "Type=simple"
      echo "SyslogIdentifier=forge-fleet-user"
      echo "Environment=PYTHONUNBUFFERED=1"
      echo "WorkingDirectory=$esc_dest"
      echo "EnvironmentFile=-${ENV_DIR}/forge-fleet.env"
      echo "ExecStart=$esc_py -m fleet_server --host $esc_host --port $FLEET_USER_PORT --data-dir $esc_data"
      echo "Restart=on-failure"
      echo "RestartSec=5"
      echo "StartLimitIntervalSec=120"
      echo "StartLimitBurst=8"
      echo "TimeoutStopSec=30"
      echo ""
      echo "[Install]"
      echo "WantedBy=default.target"
    } >"$UFILE"

    install -m0644 "$UFILE" "$UNIT_DIR/forge-fleet.service"
    rm -f "$UFILE"

    TTSVC="$(mktemp "${TMPDIR:-/tmp}/forge-fleet-telemetry.service.XXXXXX")"
    {
      echo "[Unit]"
      echo "Description=Forge Fleet — SQLite telemetry sample (one-shot)"
      echo "After=network.target"
      echo ""
      echo "[Service]"
      echo "Type=oneshot"
      echo "SyslogIdentifier=forge-fleet-telemetry"
      echo "Environment=PYTHONUNBUFFERED=1"
      echo "WorkingDirectory=$esc_dest"
      echo "EnvironmentFile=-${ENV_DIR}/forge-fleet.env"
      echo "ExecStart=$esc_py -m fleet_server.telemetry_sampler --data-dir $esc_data"
    } >"$TTSVC"
    install -m0644 "$TTSVC" "$UNIT_DIR/forge-fleet-telemetry.service"
    rm -f "$TTSVC"

    TTMER="$(mktemp "${TMPDIR:-/tmp}/forge-fleet-telemetry.timer.XXXXXX")"
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
    } >"$TTMER"
    install -m0644 "$TTMER" "$UNIT_DIR/forge-fleet-telemetry.timer"
    rm -f "$TTMER"

    systemctl --user daemon-reload
    echo "[install-user] unit -> $UNIT_DIR/forge-fleet.service ($FLEET_USER_HOST:$FLEET_USER_PORT)"
    echo "[install-user] env (optional): $ENV_DIR/forge-fleet.env"

    if systemctl --user enable --now forge-fleet-telemetry.timer 2>/dev/null; then
      echo "[install-user] enabled forge-fleet-telemetry.timer → SQLite telemetry (incl. when HTTP is stopped)"
    else
      echo "[install-user] warning: could not enable forge-fleet-telemetry.timer" >&2
    fi

    if [[ "$RESTART_SERVICE" -eq 1 ]]; then
      systemctl --user enable forge-fleet.service 2>/dev/null || true
      if systemctl --user restart forge-fleet.service; then
        echo "[install-user] restarted forge-fleet.service (user)"
      else
        echo "[install-user] restart failed; try: systemctl --user start forge-fleet.service" >&2
      fi
    else
      echo "[install-user] skipped restart; run: systemctl --user restart forge-fleet.service"
    fi

    echo "[install-user] status: systemctl --user status forge-fleet.service"
    echo "[install-user] at login boot: already enabled default.target; for headless boot run once: loginctl enable-linger $USER"
  fi
elif [[ "$INSTALL_SYSTEMD" -eq 1 ]] && [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[install-user] dry-run: skipped user unit and restart"
fi
