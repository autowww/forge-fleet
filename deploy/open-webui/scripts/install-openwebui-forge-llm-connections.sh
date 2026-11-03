#!/usr/bin/env bash
# Wire Open WebUI to bearer-secured forge-gateway (Granite catalog pins) + optional web bridges.
# Run on Granite after forge-llm control plane and Open WebUI compose exist.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$DEPLOY/../.." && pwd)"
BEARER_DIR="${FORGE_OPEN_WEBUI_BEARER_DIR:-${HOME}/.config/forge-open-webui}"
GW_ENV="${BEARER_DIR}/forge-llm-gateway.env"
CP_ROOT="${FORGE_LLM_CONTROL_PLANE_ROOT:-$REPO_ROOT/deploy/forge-llm-control-plane}"
CP_ENV="$CP_ROOT/.env"
WEBUI_ENV="$DEPLOY/.env"
GATEWAY_PORT="${FORGE_GATEWAY_HOST_PORT:-18080}"
DRY_RUN="${DRY_RUN:-0}"

mkdir -p "$BEARER_DIR"
chmod 700 "$BEARER_DIR"

if [[ ! -f "$GW_ENV" ]]; then
  token="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  umask 077
  printf 'FORGE_LLM_GATEWAY_BEARER=%s\n' "$token" >"$GW_ENV"
  chmod 600 "$GW_ENV"
  echo "Created $GW_ENV"
else
  # shellcheck disable=SC1090
  set -a && source "$GW_ENV" && set +a
  echo "Using existing $GW_ENV"
fi

# shellcheck disable=SC1090
set -a && source "$GW_ENV" && set +a
[[ -n "${FORGE_LLM_GATEWAY_BEARER:-}" ]] || {
  echo "FORGE_LLM_GATEWAY_BEARER missing in $GW_ENV" >&2
  exit 1
}

render_py="$SCRIPT_DIR/render-forge-llm-openwebui-env.py"
json="$("$render_py" --bearer-file "$GW_ENV" --gateway-port "$GATEWAY_PORT" --json)"
base_urls="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["OPENAI_API_BASE_URLS"])' <<<"$json")"
joined_keys="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["OPENAI_API_KEYS"])' <<<"$json")"

upsert_env() {
  local file="$1"
  local key="$2"
  local val="$3"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "would set $key in $file"
    return
  fi
  touch "$file"
  if grep -q "^${key}=" "$file" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$file"
  else
    printf '%s=%s\n' "$key" "$val" >>"$file"
  fi
}

[[ -f "$WEBUI_ENV" ]] || cp "$DEPLOY/.env.example" "$WEBUI_ENV"

upsert_env "$WEBUI_ENV" "OPENAI_API_BASE_URLS" "$base_urls"
upsert_env "$WEBUI_ENV" "OPENAI_API_KEYS" "$joined_keys"
upsert_env "$WEBUI_ENV" "ENABLE_OPENAI_API" "true"
upsert_env "$WEBUI_ENV" "ENABLE_OLLAMA_API" "false"
upsert_env "$WEBUI_ENV" "ENABLE_API_KEYS" "true"
upsert_env "$WEBUI_ENV" "ENABLE_API_KEYS_ENDPOINT_RESTRICTIONS" "true"
upsert_env "$WEBUI_ENV" "API_KEYS_ALLOWED_ENDPOINTS" "/api/chat/completions,/api/models"

mkdir -p "$(dirname "$CP_ENV")"
touch "$CP_ENV"
upsert_env "$CP_ENV" "FORGE_API_TOKEN" "$FORGE_LLM_GATEWAY_BEARER"
upsert_env "$CP_ENV" "GATEWAY_AUTH_REQUIRED" "true"
upsert_env "$CP_ENV" "GATEWAY_PORT" "$GATEWAY_PORT"
upsert_env "$CP_ENV" "FORGE_LLM_EXPOSE_PINNED_MODELS_ONLY" "true"

echo ""
echo "Open WebUI connections (bearer-secured):"
echo "  1) forge-gateway  http://host.docker.internal:${GATEWAY_PORT}/v1"
idx=2
for bridge_env in "$BEARER_DIR"/bridge-*.env; do
  [[ -f "$bridge_env" ]] || continue
  slug="${bridge_env##*/bridge-}"
  slug="${slug%.env}"
  echo "  ${idx}) web bridge account ${slug} (see bridge unit port)"
  idx=$((idx + 1))
done
echo ""
echo "Next:"
echo "  cd $CP_ROOT && docker compose up -d --build forge-gateway"
echo "  cd $DEPLOY && docker compose -f compose.yaml -f compose.granite.yaml up -d"
echo "  Open WebUI → Admin → Connections: verify OpenAI connection(s); Ollama should stay OFF."
echo "  Chat models: see config/forge-llm-granite-openwebui.yaml (ids match runner artifact_pins)."
echo ""
echo "Smoke (on Granite loopback):"
echo "  curl -fsS -H \"Authorization: Bearer \$(
    grep FORGE_LLM_GATEWAY_BEARER "$GW_ENV" | cut -d= -f2-
  )\" http://127.0.0.1:${GATEWAY_PORT}/v1/models"
