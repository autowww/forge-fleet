#!/usr/bin/env bash
# Tunnel Granite headless Chromium CDP to this laptop and open Playwright Inspector for sign-in.
#
# Usage (from forge-fleet/):
#   ./deploy/open-webui/scripts/granite-open-webui-auth-laptop.sh chatgpt-primary
#   ./deploy/open-webui/scripts/granite-open-webui-auth-laptop.sh gemini-primary
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACCOUNT="${1:?usage: $0 chatgpt-primary|gemini-primary}"
SSH_HOST="${GRANITE_SSH_HOST:-granite}"

case "$ACCOUNT" in
  chatgpt|chatgpt-primary) REMOTE_PORT=9230 LOCAL_PORT=19230 ;;
  gemini|gemini-primary) REMOTE_PORT=9231 LOCAL_PORT=19231 ;;
  *) echo "unknown account $ACCOUNT" >&2; exit 1 ;;
esac

cdp_ok() {
  curl -fsS -m 3 "http://127.0.0.1:${LOCAL_PORT}/json/version" 2>/dev/null | grep -q '"Browser"'
}

close_stale_forward() {
  local pids
  pids="$(ss -lptn "sport = :${LOCAL_PORT}" 2>/dev/null | awk -Fpid= '{print $2}' | awk '{print $1}' | tr -d ')' | sort -u || true)"
  if [[ -n "${pids// }" ]]; then
    echo "Closing stale listener on :${LOCAL_PORT} (pid ${pids})..."
    kill $pids 2>/dev/null || true
    sleep 1
  fi
}

open_tunnel() {
  echo "Opening SSH tunnel localhost:${LOCAL_PORT} → ${SSH_HOST}:127.0.0.1:${REMOTE_PORT}"
  ssh -f -N -o ExitOnForwardFailure=yes \
    -L "127.0.0.1:${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}" \
    "$SSH_HOST"
  sleep 1
}

if cdp_ok; then
  echo "Reusing existing CDP tunnel on :${LOCAL_PORT}"
elif ss -lptn "sport = :${LOCAL_PORT}" 2>/dev/null | grep -q LISTEN; then
  close_stale_forward
  open_tunnel
else
  open_tunnel
fi

if ! cdp_ok; then
  echo "CDP not reachable on :${LOCAL_PORT}. On Granite (as administrator):" >&2
  echo "  systemctl --user restart forge-open-webui-edge-${ACCOUNT}.service" >&2
  exit 1
fi

curl -fsS -m 5 "http://127.0.0.1:${LOCAL_PORT}/json/version" | head -c 120
echo ""

PYTHON=""
for candidate in \
  "${HOME}/Code/forge-lcdl/.venv/bin/python3" \
  "${SCRIPT_DIR}/../../../.venv/bin/python3" \
  python3; do
  if [[ -x "$candidate" ]] && "$candidate" -c "import playwright" 2>/dev/null; then
    PYTHON="$candidate"
    break
  fi
done
if [[ -z "$PYTHON" ]]; then
  echo "Playwright not found. Run:" >&2
  echo "  cd ~/Code/forge-lcdl && pip install -e '.[playwright]' && playwright install chromium" >&2
  exit 2
fi

exec "$PYTHON" "$SCRIPT_DIR/granite-open-webui-auth-laptop.py" "$ACCOUNT"
