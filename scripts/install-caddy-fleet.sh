#!/usr/bin/env bash
# Interactive (or env-driven) Caddy install for Forge Fleet on Ubuntu.
# - User layout: systemd --user, Fleet on 127.0.0.1:<fleet_port>, Caddy HTTP :<caddy_port> (all interfaces).
# - System layout: systemd system, Caddy -> 127.0.0.1:18765 (requires root; writes /etc/forge-fleet/*).
#
# Interactive (default):
#   ./scripts/install-caddy-fleet.sh
#
# Non-interactive (e.g. CI / remote script):
#   LAYOUT=user FLEET_BEARER_TOKEN='secret' ./scripts/install-caddy-fleet.sh --non-interactive
#   LAYOUT=system FLEET_BEARER_TOKEN='secret' sudo -E ./scripts/install-caddy-fleet.sh --non-interactive
#
# Optional env: FLEET_UPSTREAM_HOST FLEET_UPSTREAM_PORT CADDY_PUBLIC_PORT INSTALL_CADDY_APT=1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

INTERACTIVE=1
LAYOUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --non-interactive|-n) INTERACTIVE=0; shift ;;
    --layout)
      LAYOUT="${2:-}"
      shift 2
      ;;
    -h|--help)
      sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown option: $1 (try --help)" >&2
      exit 2
      ;;
  esac
done

die() { echo "install-caddy-fleet: $*" >&2; exit 1; }

export INSTALL_CADDY_APT="${INSTALL_CADDY_APT:-1}"

upsert_env_line() {
  local key="$1" val="$2" file="$3"
  mkdir -p "$(dirname "$file")"
  touch "$file"
  if grep -qE "^[[:space:]]*${key}=" "$file" 2>/dev/null; then
    sed -i "/^[[:space:]]*${key}=/d" "$file"
  fi
  printf '%s=%s\n' "$key" "$val" >>"$file"
  chmod 0600 "$file"
}

ensure_caddy() {
  if command -v caddy >/dev/null 2>&1; then
    return 0
  fi
  if [[ "${INSTALL_CADDY_APT:-}" == "0" ]]; then
    die "caddy not on PATH; install it (e.g. sudo apt install caddy) or set INSTALL_CADDY_APT=1"
  fi
  if [[ "${INTERACTIVE}" -eq 1 ]]; then
    read -rp "Install Caddy via apt (needs sudo)? [Y/n]: " ans
    case "${ans:-y}" in
      [Nn]*) die "Install caddy manually, then re-run." ;;
    esac
  fi
  if ! command -v sudo >/dev/null; then
    die "sudo not found; install caddy manually"
  fi
  sudo apt-get update -qq
  sudo apt-get install -y caddy
}

write_user_unit_and_caddyfile() {
  local upstream_host="$1" upstream_port="$2" public_port="$3"
  local cfg_dir="${XDG_CONFIG_HOME:-$HOME/.config}/forge-fleet"
  local unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  local env_file="$cfg_dir/forge-fleet.env"
  local caddyfile="$cfg_dir/Caddyfile.caddy-fleet"
  local unit_file="$unit_dir/forge-fleet-caddy.service"

  mkdir -p "$cfg_dir" "$unit_dir"

  cat >"$caddyfile" <<EOF
{
	admin off
}

:${public_port} {
	encode gzip
	reverse_proxy ${upstream_host}:${upstream_port} {
		header_up Authorization "Bearer {\$FLEET_BEARER_TOKEN}"
	}
}
EOF

  cat >"$unit_file" <<EOF
[Unit]
Description=Caddy — Forge Fleet reverse proxy (user, HTTP :${public_port})
After=network-online.target forge-fleet.service
Wants=forge-fleet.service

[Service]
Type=simple
EnvironmentFile=-%h/.config/forge-fleet/forge-fleet.env
ExecStart=/usr/bin/caddy run --environ --config %h/.config/forge-fleet/Caddyfile.caddy-fleet
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF

  command -v caddy >/dev/null || die "caddy not on PATH"
  # shellcheck disable=SC1090
  set -a
  # shellcheck source=/dev/null
  source "$env_file" || true
  set +a
  if ! caddy validate --environ --config "$caddyfile" 2>&1; then
    die "caddy validate failed — fix Caddyfile or $env_file; logs: journalctl --user -xeu forge-fleet-caddy.service"
  fi
}

write_system_caddyfile() {
  local public_port="$1"
  local upstream_host="${2:-127.0.0.1}"
  local upstream_port="${3:-18765}"
  install -d -m0755 /etc/forge-fleet
  cat >/etc/forge-fleet/Caddyfile <<EOF
{
	admin off
}

:${public_port} {
	encode gzip
	reverse_proxy ${upstream_host}:${upstream_port} {
		header_up Authorization "Bearer {\$FLEET_BEARER_TOKEN}"
	}
}
EOF
  chmod 0644 /etc/forge-fleet/Caddyfile
}

run_user_systemd() {
  systemctl --user daemon-reload
  systemctl --user enable forge-fleet-caddy.service
  systemctl --user restart forge-fleet-caddy.service
  echo ""
  echo "Started: systemctl --user status forge-fleet-caddy.service"
  systemctl --user --no-pager --full status forge-fleet-caddy.service || true
}

run_system_systemd() {
  local unit_src="$REPO_ROOT/systemd/forge-fleet-caddy.service"
  [[ -f "$unit_src" ]] || die "missing $unit_src"
  install -m0644 "$unit_src" /etc/systemd/system/forge-fleet-caddy.service
  systemctl daemon-reload
  systemctl enable forge-fleet-caddy.service
  systemctl restart forge-fleet-caddy.service
  echo ""
  echo "Started: systemctl status forge-fleet-caddy.service"
  systemctl --no-pager --full status forge-fleet-caddy.service || true
}

prompt_layout() {
  echo ""
  echo "=== Forge Fleet + Caddy ==="
  echo "1) User Fleet   — Fleet via install-user.sh (127.0.0.1:<fleet port>), Caddy on a different HTTP port (systemd --user)"
  echo "2) System Fleet — Fleet on 127.0.0.1:18765 (after drop-in), Caddy HTTP on a public port (systemd system, needs sudo)"
  read -rp "Choose [1]: " n
  case "${n:-1}" in
    2) LAYOUT=system ;;
    *) LAYOUT=user ;;
  esac
}

read_bearer() {
  local env_file="${1:-}"
  local existing=""
  if [[ -n "$env_file" && -f "$env_file" ]] && grep -qE '^[[:space:]]*FLEET_BEARER_TOKEN=[^[:space:]]+' "$env_file" 2>/dev/null; then
    existing="(existing file — Enter to keep, or type new token)"
  fi
  echo ""
  echo "Enter FLEET_BEARER_TOKEN ${existing}"
  read -rs token || true
  echo ""
  if [[ -n "${token// }" ]]; then
    FLEET_BEARER_TOKEN="$token"
  elif [[ -n "${FLEET_BEARER_TOKEN:-}" ]]; then
    :
  elif [[ -n "$env_file" && -f "$env_file" ]]; then
    FLEET_BEARER_TOKEN="$(grep -E '^[[:space:]]*FLEET_BEARER_TOKEN=' "$env_file" | head -1 | sed 's/^[^=]*=//')"
  fi
  [[ -n "${FLEET_BEARER_TOKEN// }" ]] || die "FLEET_BEARER_TOKEN is required"
}

prompt_user_ports() {
  read -rp "Fleet upstream host [127.0.0.1]: " h
  FLEET_UPSTREAM_HOST="${h:-127.0.0.1}"
  read -rp "Fleet upstream port (user install default) [18766]: " p
  FLEET_UPSTREAM_PORT="${p:-18766}"
  read -rp "Caddy public HTTP port (must differ from Fleet) [18767]: " c
  CADDY_PUBLIC_PORT="${c:-18767}"
  if [[ "$CADDY_PUBLIC_PORT" == "$FLEET_UPSTREAM_PORT" ]]; then
    die "Caddy public port must differ from Fleet port"
  fi
}

prompt_system_ports() {
  read -rp "Fleet upstream host [127.0.0.1]: " h
  FLEET_UPSTREAM_HOST="${h:-127.0.0.1}"
  read -rp "Fleet upstream port [18765]: " p
  FLEET_UPSTREAM_PORT="${p:-18765}"
  read -rp "Caddy public HTTP port [18766]: " c
  CADDY_PUBLIC_PORT="${c:-18766}"
}

prompt_enforce_user() {
  local env_file="$1"
  read -rp "Add FLEET_ENFORCE_BEARER=1 so /v1/* checks bearer behind Caddy? [Y/n]: " e
  case "${e:-y}" in
    [Nn]*) ;;
    *) upsert_env_line FLEET_ENFORCE_BEARER 1 "$env_file" ;;
  esac
}

# --- defaults for non-interactive ---
FLEET_UPSTREAM_HOST="${FLEET_UPSTREAM_HOST:-127.0.0.1}"
FLEET_UPSTREAM_PORT="${FLEET_UPSTREAM_PORT:-}"
CADDY_PUBLIC_PORT="${CADDY_PUBLIC_PORT:-}"
FLEET_BEARER_TOKEN="${FLEET_BEARER_TOKEN:-}"

if [[ "$INTERACTIVE" -eq 1 ]]; then
  [[ -n "$LAYOUT" ]] || prompt_layout
else
  [[ -n "${LAYOUT:-}" ]] || die "Set LAYOUT=user or LAYOUT=system for --non-interactive"
fi

LAYOUT="${LAYOUT:?}"

case "$LAYOUT" in
  user)
    CFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/forge-fleet"
    ENV_FILE="$CFG_DIR/forge-fleet.env"
    FLEET_UPSTREAM_PORT="${FLEET_UPSTREAM_PORT:-18766}"
    CADDY_PUBLIC_PORT="${CADDY_PUBLIC_PORT:-18767}"

    if [[ "$INTERACTIVE" -eq 1 ]]; then
      mkdir -p "$CFG_DIR"
      if [[ ! -f "$ENV_FILE" ]]; then
        read -rp "Create $ENV_FILE from repo example? [Y/n]: " mk
        case "${mk:-y}" in
          [Nn]*) ;;
          *)
            if [[ -f "$REPO_ROOT/systemd/environment.example" ]]; then
              install -m0600 "$REPO_ROOT/systemd/environment.example" "$ENV_FILE"
            else
              install -m0600 /dev/null "$ENV_FILE"
            fi
            ;;
        esac
      fi
      read_bearer "$ENV_FILE"
      upsert_env_line FLEET_BEARER_TOKEN "$FLEET_BEARER_TOKEN" "$ENV_FILE"
      prompt_user_ports
      prompt_enforce_user "$ENV_FILE"
    else
      [[ -f "$ENV_FILE" ]] || die "missing $ENV_FILE (create via install-user.sh or copy environment.example)"
      if [[ -z "${FLEET_BEARER_TOKEN// }" ]]; then
        read_bearer "$ENV_FILE"
      fi
      upsert_env_line FLEET_BEARER_TOKEN "$FLEET_BEARER_TOKEN" "$ENV_FILE"
    fi

    [[ "$CADDY_PUBLIC_PORT" != "$FLEET_UPSTREAM_PORT" ]] || die "Caddy port must differ from Fleet port"

    ensure_caddy
    write_user_unit_and_caddyfile "$FLEET_UPSTREAM_HOST" "$FLEET_UPSTREAM_PORT" "$CADDY_PUBLIC_PORT"
    run_user_systemd

    echo ""
    echo "Public URL (all interfaces): http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo THIS_HOST):${CADDY_PUBLIC_PORT}/"
    echo "Upstream Fleet: http://${FLEET_UPSTREAM_HOST}:${FLEET_UPSTREAM_PORT}/"
    echo "Boot without login session: loginctl enable-linger $USER"
    if systemctl --user is-active --quiet forge-fleet.service 2>/dev/null; then
      if [[ "$INTERACTIVE" -eq 1 ]]; then
        read -rp "Restart user forge-fleet.service to pick up env? [Y/n]: " rs
        case "${rs:-y}" in
          [Nn]*) ;;
          *) systemctl --user restart forge-fleet.service && echo "forge-fleet.service restarted." ;;
        esac
      else
        systemctl --user restart forge-fleet.service && echo "forge-fleet.service restarted."
      fi
    fi
    ;;

  system)
    [[ "$(id -u)" -eq 0 ]] || die "System layout requires root: sudo -E $0 $*"
    FLEET_UPSTREAM_PORT="${FLEET_UPSTREAM_PORT:-18765}"
    CADDY_PUBLIC_PORT="${CADDY_PUBLIC_PORT:-18766}"

    if [[ "$INTERACTIVE" -eq 1 ]]; then
      read_bearer "/etc/forge-fleet/caddy.env"
      prompt_system_ports
    else
      [[ -n "${FLEET_BEARER_TOKEN// }" ]] || die "Set FLEET_BEARER_TOKEN for system layout"
    fi

    ensure_caddy
    install -d -m0755 /etc/forge-fleet
    umask 077
    printf 'FLEET_BEARER_TOKEN=%s\n' "$FLEET_BEARER_TOKEN" >/etc/forge-fleet/caddy.env
    umask 022
    if id -u caddy &>/dev/null; then
      chown root:caddy /etc/forge-fleet/caddy.env
      chmod 0640 /etc/forge-fleet/caddy.env
    else
      chmod 0600 /etc/forge-fleet/caddy.env
    fi

    write_system_caddyfile "$CADDY_PUBLIC_PORT" "$FLEET_UPSTREAM_HOST" "$FLEET_UPSTREAM_PORT"
    run_system_systemd

    echo ""
    echo "Public URL: http://0.0.0.0:${CADDY_PUBLIC_PORT}/ -> http://${FLEET_UPSTREAM_HOST}:${FLEET_UPSTREAM_PORT}/"
    ;;

  *) die "LAYOUT must be user or system (got $LAYOUT)" ;;
esac
