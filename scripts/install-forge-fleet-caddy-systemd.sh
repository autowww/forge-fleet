#!/usr/bin/env bash
# Install Caddy as systemd service forge-fleet-caddy: HTTP on :18766, all interfaces,
# reverse_proxy -> 127.0.0.1:18765 with Authorization: Bearer <token>.
#
# Prerequisites: apt install caddy (or caddy on PATH), user caddy exists, forge-fleet.service
# listening on 127.0.0.1:18765 (see docs/CADDY-SYSTEMD.md).
#
# Usage (from checkout, or after files exist under /opt/forge-fleet):
#   FLEET_BEARER_TOKEN='your-secret' sudo -E ./scripts/install-forge-fleet-caddy-systemd.sh
#   sudo ./scripts/install-forge-fleet-caddy-systemd.sh 'your-secret'

set -euo pipefail

TOKEN="${FLEET_BEARER_TOKEN:-${1:-}}"
if [[ -z "${TOKEN// }" ]]; then
  echo "Set FLEET_BEARER_TOKEN or pass token as first argument (same value as /etc/forge-fleet/forge-fleet.env)." >&2
  exit 1
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo FLEET_BEARER_TOKEN=... $0" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
UNIT_SRC="$REPO_ROOT/systemd/forge-fleet-caddy.service"
CF_SRC="$REPO_ROOT/systemd/Caddyfile.forge-fleet.example"

[[ -f "$UNIT_SRC" ]] || { echo "missing $UNIT_SRC" >&2; exit 1; }
[[ -f "$CF_SRC" ]] || { echo "missing $CF_SRC" >&2; exit 1; }

install -d -m0755 /etc/forge-fleet

umask 077
printf 'FLEET_BEARER_TOKEN=%s\n' "$TOKEN" >/etc/forge-fleet/caddy.env
umask 022

if id -u caddy &>/dev/null; then
  chown root:caddy /etc/forge-fleet/caddy.env
  chmod 0640 /etc/forge-fleet/caddy.env
else
  echo "warning: user caddy not found; caddy.env left root:root 0600 (fix ownership if you add user caddy)" >&2
  chmod 0600 /etc/forge-fleet/caddy.env
fi

install -m0644 "$CF_SRC" /etc/forge-fleet/Caddyfile
install -m0644 "$UNIT_SRC" /etc/systemd/system/forge-fleet-caddy.service

systemctl daemon-reload
systemctl enable forge-fleet-caddy.service
systemctl restart forge-fleet-caddy.service

echo "forge-fleet-caddy: enabled + started. HTTP on all interfaces: http://0.0.0.0:18766/ -> http://127.0.0.1:18765/"
systemctl --no-pager --full status forge-fleet-caddy.service || true
