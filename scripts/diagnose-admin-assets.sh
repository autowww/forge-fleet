#!/usr/bin/env bash
# diagnose-admin-assets.sh — collect evidence when /admin/ loads but looks unstyled.
# Run on the machine where fleet-server runs (no sudo). Paste full output into a ticket/chat.
#
# Usage:
#   ./scripts/diagnose-admin-assets.sh
#   ./scripts/diagnose-admin-assets.sh 18767
#   FLEET_SRC=~/forge-fleet FLEET_USER_DEST=~/.local/share/forge-fleet ./scripts/diagnose-admin-assets.sh
#
# Optional:
#   FLEET_SRC          — git checkout (default: dir containing this script)
#   FLEET_USER_DEST    — user install tree (default: ~/.local/share/forge-fleet)
#   CURL_EXTRA_BIND    — if set (e.g. 192.168.1.10), also GET assets via this host (same port)

set -euo pipefail

echo "========== Forge Fleet — admin UI asset diagnostics =========="
echo "time: $(date -Iseconds 2>/dev/null || date)"
echo "host: $(hostname -f 2>/dev/null || hostname)"
echo "user: $(whoami)"
echo

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FLEET_SRC="${FLEET_SRC:-$SCRIPT_DIR}"
FLEET_USER_DEST="${FLEET_USER_DEST:-$HOME/.local/share/forge-fleet}"
UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/forge-fleet.service"

PORT="${1:-}"
HOST="127.0.0.1"

if [[ -z "$PORT" ]] && [[ -f "$UNIT" ]]; then
  EX="$(grep -E '^ExecStart=' "$UNIT" 2>/dev/null || true)"
  echo "--- systemd user unit (ExecStart) ---"
  echo "$EX"
  if [[ -n "$EX" ]]; then
    # shellcheck disable=SC2001
    P="$(echo "$EX" | sed -n 's/.*--port[[:space:]]\+\([0-9]\+\).*/\1/p')"
    # shellcheck disable=SC2001
    H="$(echo "$EX" | sed -n 's/.*--host[[:space:]]\+\([^[:space:]]\+\).*/\1/p')"
    [[ -n "$P" ]] && PORT="$P"
    [[ -n "$H" ]] && HOST="$H"
  fi
  echo
fi

PORT="${PORT:-${FLEET_PORT:-18766}}"
echo "--- effective target ---"
echo "HOST=$HOST  PORT=$PORT  (override: $0 <port> or set FLEET_PORT)"
echo "FLEET_SRC=$FLEET_SRC"
echo "FLEET_USER_DEST=$FLEET_USER_DEST"
echo

echo "--- on-disk kitchensink (needed for /admin/ks/css) ---"
for row in \
  "checkout|$FLEET_SRC/kitchensink/css/forge-theme.css" \
  "checkout|$FLEET_SRC/kitchensink/css/forge-fleet-admin.css" \
  "user install|$FLEET_USER_DEST/kitchensink/css/forge-theme.css" \
  "user install|$FLEET_USER_DEST/kitchensink/css/forge-fleet-admin.css"; do
  label="${row%%|*}"
  path="${row#*|}"
  if [[ -f "$path" ]]; then
    echo "OK $label: $path ($(wc -c <"$path") bytes)"
  else
    echo "MISSING $label: $path"
  fi
done
if [[ -d "$FLEET_SRC/kitchensink" ]]; then
  echo "kitchensink dir in checkout: $(find "$FLEET_SRC/kitchensink/css" -maxdepth 1 -name '*.css' 2>/dev/null | wc -l) css files in kitchensink/css/"
else
  echo "MISSING directory: $FLEET_SRC/kitchensink (run: git submodule update --init --recursive)"
fi
echo

echo "--- HTTP from fleet (expect 200 for HTML and /admin/ks/css/*) ---"
check_url() {
  local name="$1" url="$2"
  local code ct len err
  code="$(curl -sS -o /tmp/fleet-diag-body.$$ -w "%{http_code}" --connect-timeout 5 "$url" 2>/tmp/fleet-diag-err.$$ || true)"
  ct="$(file -b --mime-type /tmp/fleet-diag-body.$$ 2>/dev/null || echo "?")"
  len="$(wc -c </tmp/fleet-diag-body.$$ 2>/dev/null || echo 0)"
  err="$(cat /tmp/fleet-diag-err.$$ 2>/dev/null || true)"
  rm -f /tmp/fleet-diag-body.$$ /tmp/fleet-diag-err.$$
  printf "%s\n" "  $name"
  printf "    url: %s\n" "$url"
  printf "    http_code=%s  bytes=%s  mime=%s\n" "$code" "$len" "$ct"
  if [[ -n "$err" ]]; then
    printf "    curl_err: %s\n" "$(echo "$err" | head -n 3)"
  fi
}

BASE="http://${HOST}:${PORT}"
check_url "admin HTML" "$BASE/admin/"
check_url "forge-theme.css" "$BASE/admin/ks/css/forge-theme.css"
check_url "forge-fleet-admin.css" "$BASE/admin/ks/css/forge-fleet-admin.css"

echo "--- Bootstrap CDN (browser loads this from the internet) ---"
check_url "jsdelivr bootstrap css" "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"

if [[ -n "${CURL_EXTRA_BIND:-}" ]]; then
  echo "--- extra bind (LAN IP) — same paths, port $PORT ---"
  EB="http://${CURL_EXTRA_BIND}:${PORT}"
  check_url "admin HTML (via CURL_EXTRA_BIND)" "$EB/admin/"
  check_url "forge-theme.css (via CURL_EXTRA_BIND)" "$EB/admin/ks/css/forge-theme.css"
fi

echo
echo "--- listener (who is on port $PORT?) ---"
if command -v ss >/dev/null 2>&1; then
  ss -tlnp 2>/dev/null | grep -E ":${PORT}\\b" || echo "  (no match for :$PORT)"
elif command -v netstat >/dev/null 2>&1; then
  netstat -tlnp 2>/dev/null | grep -E ":${PORT}\\b" || echo "  (no match)"
else
  echo "  (install ss or netstat to see listeners)"
fi

echo
echo "--- non-loopback IPs (for LAN access you usually need --host 0.0.0.0) ---"
ip -4 addr show 2>/dev/null | sed -n 's/^[[:space:]]*inet \([0-9.]*\).*/\1/p' | grep -v '^127\.' || true

echo
echo "========== end (paste everything above) =========="
