#!/usr/bin/env bash
# Push forge-gateway OpenAI URL + bearer into Open WebUI Postgres (env alone is not enough after first boot).
set -euo pipefail

GW_ENV="${FORGE_OPEN_WEBUI_BEARER_DIR:-${HOME}/.config/forge-open-webui}/forge-llm-gateway.env"
PG_CONTAINER="${OPEN_WEBUI_PG_CONTAINER:-forge-open-webui-postgres}"

if [[ ! -f "$GW_ENV" ]]; then
  echo "missing $GW_ENV — run install-openwebui-forge-llm-connections.sh first" >&2
  exit 1
fi
# shellcheck disable=SC1090
set -a && source "$GW_ENV" && set +a
[[ -n "${FORGE_LLM_GATEWAY_BEARER:-}" ]] || {
  echo "FORGE_LLM_GATEWAY_BEARER empty" >&2
  exit 1
}

OPENAI_URL="${OPENWEBUI_FORGE_GATEWAY_URL:-http://forge-gateway:8080/v1}"
OLLAMA_URL="${OPENWEBUI_OLLAMA_URL:-http://forge-ollama-host:11434}"
ENABLE_OLLAMA="${OPENWEBUI_ENABLE_OLLAMA:-true}"

docker network connect forge-open-webui_default forge-ollama-host 2>/dev/null || true
docker network connect forge-open-webui_default forge-gateway 2>/dev/null || true

docker exec "$PG_CONTAINER" psql -U open_webui -d open_webui -v ON_ERROR_STOP=1 \
  -v openai_url="$OPENAI_URL" \
  -v bearer="$FORGE_LLM_GATEWAY_BEARER" \
  -v ollama_url="$OLLAMA_URL" \
  -v enable_ollama="$ENABLE_OLLAMA" <<'SQL'
UPDATE config SET value = 'true'::json WHERE key = 'openai.enable';
UPDATE config SET value = json_build_array(:'openai_url') WHERE key = 'openai.api_base_urls';
UPDATE config SET value = json_build_array(:'bearer') WHERE key = 'openai.api_keys';
UPDATE config SET value = to_json(:enable_ollama::boolean) WHERE key = 'ollama.enable';
UPDATE config SET value = json_build_array(:'ollama_url') WHERE key = 'ollama.base_urls';
UPDATE config SET value = '{"0": {"enable": true, "prefix_id": "forge-llm", "provider": "openai"}}'::json WHERE key = 'openai.api_configs';
SQL

echo "Open WebUI DB connections synced (OpenAI -> ${OPENAI_URL})"
