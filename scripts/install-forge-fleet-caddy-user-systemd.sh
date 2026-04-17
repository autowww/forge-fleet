#!/usr/bin/env bash
# Caddy as systemd --user (Ubuntu-friendly): HTTP on a public port, proxy to user Fleet on loopback.
#
# Defaults match install-user.sh: Fleet at 127.0.0.1:18766. Caddy listens on :18767 (all interfaces).
# Uses the same ~/.config/forge-fleet/forge-fleet.env as fleet (FLEET_BEARER_TOKEN for Caddyfile {$FLEET_BEARER_TOKEN}).
#
# Prerequisites:
#   - sudo apt install caddy   (binary only; this unit runs caddy as YOUR user, not the caddy system user)
#   - User Fleet: systemctl --user start forge-fleet.service (install-user.sh), FLEET_BEARER_TOKEN in forge-fleet.env
#   - Add FLEET_ENFORCE_BEARER=1 to forge-fleet.env so /v1/* still checks bearer when Caddy injects it
#
# Usage from repo root or $HOME:
#   ./scripts/install-forge-fleet-caddy-user-systemd.sh
#
# Env overrides:
#   FLEET_UPSTREAM_HOST=127.0.0.1 FLEET_UPSTREAM_PORT=18766 CADDY_PUBLIC_PORT=18767

set -euo pipefail

FLEET_UPSTREAM_HOST="${FLEET_UPSTREAM_HOST:-127.0.0.1}"
FLEET_UPSTREAM_PORT="${FLEET_UPSTREAM_PORT:-18766}"
CADDY_PUBLIC_PORT="${CADDY_PUBLIC_PORT:-18767}"

CFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/forge-fleet"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
ENV_FILE="$CFG_DIR/forge-fleet.env"
CADDYFILE="$CFG_DIR/Caddyfile.caddy-fleet"
UNIT_FILE="$UNIT_DIR/forge-fleet-caddy.service"

mkdir -p "$CFG_DIR" "$UNIT_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing $ENV_FILE — create it (see install-user.sh) and set FLEET_BEARER_TOKEN for production." >&2
  exit 1
fi

if ! grep -q '^FLEET_BEARER_TOKEN=.\+' "$ENV_FILE" 2>/dev/null; then
  echo "set a non-empty FLEET_BEARER_TOKEN in $ENV_FILE (or Caddy cannot inject Authorization)." >&2
  exit 1
fi

cat >"$CADDYFILE" <<EOF
{
	admin localhost:2019
}

:${CADDY_PUBLIC_PORT} {
	encode gzip
	reverse_proxy ${FLEET_UPSTREAM_HOST}:${FLEET_UPSTREAM_PORT} {
		header_up Authorization "Bearer {\$FLEET_BEARER_TOKEN}"
	}
}
EOF

cat >"$UNIT_FILE" <<EOF
[Unit]
Description=Caddy — Forge Fleet reverse proxy (user, HTTP :${CADDY_PUBLIC_PORT})
After=network-online.target forge-fleet.service
Wants=forge-fleet.service

[Service]
Type=notify
EnvironmentFile=-$ENV_FILE
ExecStart=/usr/bin/caddy run --environ --config $CADDYFILE
ExecReload=/usr/bin/caddy reload --config $CADDYFILE --force
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF

if ! command -v systemctl >/dev/null; then
  echo "systemctl not found" >&2
  exit 1
fi

systemctl --user daemon-reload
systemctl --user enable forge-fleet-caddy.service
systemctl --user restart forge-fleet-caddy.service

echo "forge-fleet-caddy (user): http://0.0.0.0:${CADDY_PUBLIC_PORT}/ -> http://${FLEET_UPSTREAM_HOST}:${FLEET_UPSTREAM_PORT}/"
echo "Boot without login:  loginctl enable-linger $USER"
systemctl --user --no-pager --full status forge-fleet-caddy.service || true
