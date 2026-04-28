#!/usr/bin/env bash
# remote-fleet-caddy-diag.sh — collect Fleet + Caddy + listener evidence on the host.
# Run on the machine where Fleet/Caddy run (needs sudo for ss / system units). Paste full output into a ticket or chat.
#
# Usage:
#   ./scripts/troubleshooting/remote-fleet-caddy-diag.sh
#   ./scripts/troubleshooting/remote-fleet-caddy-diag.sh 192.168.50.242
#
# Env:
#   FLEET_DIAG_LAN_IP   — LAN IPv4 for curl probes (default: first arg, else 192.168.50.242)

set -euo pipefail

LAN_IP="${1:-${FLEET_DIAG_LAN_IP:-192.168.50.242}}"

echo "========== Forge Fleet / Caddy — remote diagnostics =========="
echo "time: $(date -Iseconds 2>/dev/null || date)"
echo "host: $(hostname -f 2>/dev/null || hostname)"
echo "user: $(whoami)"
echo "LAN_IP (curl targets): $LAN_IP"
echo

echo "=== IPv4 addresses ==="
ip -br addr show scope global 2>/dev/null || true
echo

echo "=== TCP listeners (Fleet / Caddy / common ports) ==="
if command -v ss >/dev/null; then
  sudo ss -tlnp 2>/dev/null | grep -E ':(1876[5-9]|1877[0-9]|11735|8080|80|443)\b' \
    || echo "(no matches on scanned ports — see python/caddy lines below)"
  sudo ss -tlnp 2>/dev/null | grep -E 'fleet|caddy|python' || true
else
  echo "ss not found"
fi
echo

echo "=== User forge-fleet.service (if any) ==="
U="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/forge-fleet.service"
if [[ -f "$U" ]]; then
  echo "# $U"
  grep -E '^(ExecStart|WorkingDirectory|EnvironmentFile)=' "$U" || cat "$U"
else
  echo "(missing $U)"
fi
echo

echo "=== System forge-fleet.service (if any) ==="
S=/etc/systemd/system/forge-fleet.service
if [[ -f "$S" ]]; then
  echo "# $S"
  grep -E '^(ExecStart|WorkingDirectory|EnvironmentFile)=' "$S" || cat "$S"
else
  echo "(missing $S)"
fi
echo

echo "=== User Caddy (if any) ==="
for f in "${XDG_CONFIG_HOME:-$HOME/.config}/caddy/Caddyfile" "$HOME/.config/caddy/Caddyfile"; do
  if [[ -f "$f" ]]; then
    echo "# $f"
    grep -vE '^\s*#' "$f" | grep -vE '^\s*$' | head -80
    break
  fi
done || true
systemctl --user status caddy.service --no-pager -l 2>/dev/null | head -25 || echo "(no user caddy or not running)"
echo

echo "=== System Caddy (if any) ==="
for f in /etc/caddy/Caddyfile /usr/local/etc/caddy/Caddyfile; do
  if [[ -f "$f" ]]; then
    echo "# $f"
    grep -vE '^\s*#' "$f" | grep -vE '^\s*$' | head -80
    break
  fi
done || true
sudo systemctl status caddy.service --no-pager -l 2>/dev/null | head -25 || true
echo

echo "=== forge-fleet.env (redacted values) ==="
for e in "${XDG_CONFIG_HOME:-$HOME/.config}/forge-fleet/forge-fleet.env" /etc/forge-fleet/forge-fleet.env; do
  if [[ -f "$e" ]]; then
    echo "# $e"
    sed -E 's/^(\s*[^#[:space:]]+)=.*/\1=<redacted>/' "$e" | grep -vE '^\s*$|^\s*#'
  fi
done
echo

echo "=== HTTP probes (no Authorization header; 401 may still mean routing works) ==="
probe() {
  local name="$1" url="$2"
  local out code
  out="$(curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 3 --max-time 8 "$url" 2>&1)" || true
  code="$out"
  [[ "$out" =~ ^[0-9]{3}$ ]] || code="ERR:${out//$'\n'/ }"
  echo "$name  $url  ->  $code"
}
probe "loopback_fleet" "http://127.0.0.1:18766/v1/health"
probe "lan_fleet_direct" "http://${LAN_IP}:18766/v1/health"
probe "lan_caddy_18767" "http://${LAN_IP}:18767/v1/health"
probe "lan_http_80" "http://${LAN_IP}/v1/health"
echo

echo "=== Docker (names / published ports, first 30 lines) ==="
docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null | head -30 || echo "(docker not used or no permission)"
echo
echo "=== DONE — paste everything above =========="
