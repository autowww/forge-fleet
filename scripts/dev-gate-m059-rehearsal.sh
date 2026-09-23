#!/usr/bin/env bash
# Dev gate (5b): m051/m059 contract-drop rehearsal on market-studio-dev.
set -euo pipefail

SECRETS="${FORGE_CERTIFICATOR_ENV_FILE:-$HOME/Code/forge-certificators/example-banks/forge-certificator-secrets.env}"
if [[ -f "$SECRETS" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$SECRETS"
  set +a
fi

BASE="${FORGE_FLEET_BASE_URL:-}"
TOK="${FORGE_FLEET_BEARER_TOKEN:-}"
[[ -n "$BASE" && -n "$TOK" ]] || {
  echo "set FORGE_FLEET_BASE_URL and FORGE_FLEET_BEARER_TOKEN" >&2
  exit 1
}

GW="${BASE%/}/v1/app-gateways/market-studio-dev"
SID="market-studio-dev"

health_json() {
  curl -fsS "${GW}/health" -H "Authorization: Bearer ${TOK}"
}

echo "pre-rehearsal health"
health_json | python3 -c '
import sys, json
d = json.load(sys.stdin)
print(
    "status", d.get("status"),
    "schema", d.get("schema_version"),
    "head", d.get("schema_head"),
    "parity", d.get("dictionary_parity_ok"),
    "pending", d.get("schema_contract_pending"),
)
if d.get("dictionary_parity_ok") is not True:
    raise SystemExit("dictionary_parity_ok must be true before m059 rehearsal")
'

echo "POST ${SID} rollout (m051+m059 confirms, backup gate on)"
curl -fsS -X POST "${BASE}/v1/managed-services/${SID}/rollout" \
  -H "Authorization: Bearer ${TOK}" \
  -H "Content-Type: application/json" \
  -d '{
    "forge_market_env": "dev",
    "skip_backup": false,
    "run_schema_migrate": true,
    "confirm_attr_v3_drop": "1",
    "confirm_dictionary_drops": "1"
  }'

echo "poll maintenance-status"
for _ in $(seq 1 60); do
  sleep 10
  st="$(curl -fsS "${BASE}/v1/managed-services/${SID}/maintenance-status" \
    -H "Authorization: Bearer ${TOK}")"
  echo "$st" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("current_step"), d.get("failed"), d.get("maintenance"))'
  if echo "$st" | python3 -c 'import sys,json; d=json.load(sys.stdin); sys.exit(1 if d.get("failed") else 0 if not d.get("maintenance") else 1)'; then
    break
  fi
done

echo "post-rehearsal health (wait up to 3m for app restart)"
for _ in $(seq 1 18); do
  if health_json | python3 -c '
import sys, json
d = json.load(sys.stdin)
pending = d.get("schema_contract_pending") or []
print(
    "status", d.get("status"),
    "schema", d.get("schema_version"),
    "head", d.get("schema_head"),
    "parity", d.get("dictionary_parity_ok"),
    "pending", pending,
)
if d.get("status") != "ok":
    raise SystemExit(1)
if int(d.get("schema_version") or 0) < int(d.get("schema_head") or 0):
    raise SystemExit(2)
if pending:
    raise SystemExit(3)
'; then
    echo "dev m059 rehearsal ok"
    exit 0
  fi
  sleep 10
done
echo "dev health not ok after m059 rehearsal (check overlay app image matches schema 59)" >&2
exit 1
