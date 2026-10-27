#!/usr/bin/env bash
# Add or update webui.forgedc.net on the Granite Cloudflare tunnel (loopback Open WebUI).
#
# Usage (from forge-fleet/):
#   export CLOUDFLARE_API_TOKEN=…   # or source forge-knowledge-assistant/.env.local
#   export CF_TUNNEL_ID=07ff2cbc-4741-4737-a0e5-10a60a884efd  # Granite connector (default)
#   deploy/open-webui/scripts/apply-cf-webui-tunnel.sh [--dry-run]
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
KA_ENV="$ROOT/../forge-knowledge-assistant/.env.local"
if [[ -z "${CLOUDFLARE_API_TOKEN:-}" && -f "$KA_ENV" ]]; then
  CLOUDFLARE_API_TOKEN="$(grep -E '^CLOUDFLARE_API_TOKEN=' "$KA_ENV" | head -1 | cut -d= -f2- | tr -d '\r')"
fi

DRY=0
[[ "${1:-}" == "--dry-run" ]] && DRY=1

HOSTNAME="${CF_HOSTNAME:-webui.forgedc.net}"
ORIGIN_SERVICE="${CF_ORIGIN_SERVICE:-http://127.0.0.1:19808}"
CONNECT_TIMEOUT="${CF_CONNECT_TIMEOUT:-300}"
KEEPALIVE_TIMEOUT="${CF_KEEPALIVE_TIMEOUT:-300}"
ACCOUNT_ID="${CF_ACCOUNT_ID:-55c7a84f399231cd2b3733228d43912c}"
TUNNEL_ID="${CF_TUNNEL_ID:-07ff2cbc-4741-4737-a0e5-10a60a884efd}"

if [[ -z "${CLOUDFLARE_API_TOKEN:-}" ]]; then
  echo "Set CLOUDFLARE_API_TOKEN (e.g. source forge-knowledge-assistant/.env.local)" >&2
  exit 2
fi

api() {
  curl -sS -X "$1" "$2" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    -H "Content-Type: application/json" \
    "${@:3}"
}

echo "tunnel_id=$TUNNEL_ID hostname=$HOSTNAME origin=$ORIGIN_SERVICE"

cfg_json=$(api GET "https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/cfd_tunnel/${TUNNEL_ID}/configurations")

new_cfg=$(python3 - <<'PY' "$cfg_json" "$HOSTNAME" "$ORIGIN_SERVICE" "$CONNECT_TIMEOUT" "$KEEPALIVE_TIMEOUT"
import json, sys
raw, host, service, cto, kto = sys.argv[1:6]
data = json.loads(raw)
if not data.get("success"):
    raise SystemExit(f"fetch config failed: {data.get('errors')}")
result = (data.get("result") or {})
config = dict(result.get("config") or {})
ingress = list(config.get("ingress") or [])
ingress = [r for r in ingress if not str(r.get("service", "")).startswith("http_status")]
cto, kto = int(cto), int(kto)
found = False
out = []
for rule in ingress:
    if rule.get("hostname") == host:
        found = True
        rule = dict(rule)
        rule["service"] = service
        orq = dict(rule.get("originRequest") or {})
        orq["connectTimeout"] = cto
        orq["keepAliveTimeout"] = kto
        orq["tcpKeepAlive"] = max(orq.get("tcpKeepAlive") or 30, 30)
        orq["noTLSVerify"] = True
        rule["originRequest"] = orq
    out.append(rule)
if not found:
    out.insert(0, {
        "hostname": host,
        "service": service,
        "originRequest": {
            "connectTimeout": cto,
            "keepAliveTimeout": kto,
            "tcpKeepAlive": 30,
            "noTLSVerify": True,
        },
    })
out.append({"service": "http_status:404"})
config["ingress"] = out
print(json.dumps({"config": config}))
PY
)

echo "== proposed ingress (webui rule) =="
echo "$new_cfg" | python3 -m json.tool | head -60

if [[ "$DRY" -eq 1 ]]; then
  echo "(dry-run — no PUT)"
  exit 0
fi

put_json=$(api PUT "https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/cfd_tunnel/${TUNNEL_ID}/configurations" --data "$new_cfg")
python3 - <<'PY' "$put_json"
import json, sys
d = json.loads(sys.argv[1])
print("put ok=", d.get("success"))
if d.get("errors"):
    print(d["errors"])
    raise SystemExit(1)
PY

echo "Tunnel updated. Wait ~60–90s for connector sync."
python3 "$SCRIPT_DIR/ensure-webui-dns.py"
