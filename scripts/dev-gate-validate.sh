#!/usr/bin/env bash
# Dev gate (5a): generic rollout smoke against market-studio-dev via Fleet API.
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

echo "POST market-studio-dev rollout (skip backup for smoke)"
curl -fsS -X POST "${BASE}/v1/managed-services/market-studio-dev/rollout" \
  -H "Authorization: Bearer ${TOK}" \
  -H "Content-Type: application/json" \
  -d '{"skip_backup": true, "run_schema_migrate": "auto", "forge_market_env": "dev"}'

echo "poll maintenance-status"
for _ in $(seq 1 30); do
  sleep 5
  st="$(curl -fsS "${BASE}/v1/managed-services/market-studio-dev/maintenance-status" \
    -H "Authorization: Bearer ${TOK}")"
  echo "$st" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("current_step"), d.get("failed"), d.get("maintenance"))'
  if echo "$st" | python3 -c 'import sys,json; d=json.load(sys.stdin); sys.exit(0 if not d.get("maintenance") else 1)'; then
    break
  fi
done

GW="${BASE%/}/v1/app-gateways/market-studio-dev"
curl -fsS "${GW}/health" -H "Authorization: Bearer ${TOK}" | python3 -c '
import sys, json
d = json.load(sys.stdin)
print(
    "health", d.get("status"),
    "schema", d.get("schema_version"),
    "parity", d.get("dictionary_parity_ok"),
    "pending", d.get("schema_contract_pending"),
)
if d.get("status") != "ok" or int(d.get("schema_version") or 0) < 58:
    raise SystemExit("dev health gate failed")
'
