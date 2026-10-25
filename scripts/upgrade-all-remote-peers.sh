#!/usr/bin/env bash
# Queue POST /v1/admin/upgrade on every peer in local etc/remote-peers.json via this Fleet server.
#
# Usage (from forge-fleet repo):
#   FLEET_LOCAL_URL=http://127.0.0.1:18766 ./scripts/upgrade-all-remote-peers.sh
#   FLEET_LOCAL_BEARER=...  # when local auth is enforced
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="${FLEET_LOCAL_URL:-http://127.0.0.1:18766}"
BASE="${BASE%/}"
AUTH=()
if [[ -n "${FLEET_LOCAL_BEARER:-}" ]]; then
  AUTH=(-H "Authorization: Bearer ${FLEET_LOCAL_BEARER}")
fi

PEERS_JSON="$(curl -fsS "${AUTH[@]}" "${BASE}/v1/remote-peers")"
mapfile -t IDS < <(python3 -c 'import json,sys; d=json.load(sys.stdin); print("\n".join(p.get("id","") for p in d.get("peers",[]) if p.get("id")))' <<<"$PEERS_JSON")

if [[ ${#IDS[@]} -eq 0 ]]; then
  echo "upgrade-all-remote-peers: no remote peers configured on ${BASE}"
  exit 0
fi

BODY='{"mode":"upgrade","require_apt_channel":true,"allow_git_fallback":true,"max_wait_sec":120,"on_timeout":"abort"}'
for id in "${IDS[@]}"; do
  echo "upgrade-all-remote-peers: POST ${BASE}/v1/remote-peers/${id}/admin/upgrade"
  curl -fsS -X POST "${AUTH[@]}" \
    -H "Content-Type: application/json" \
    -d "$BODY" \
    "${BASE}/v1/remote-peers/${id}/admin/upgrade" | python3 -m json.tool | head -40
  echo ""
done
