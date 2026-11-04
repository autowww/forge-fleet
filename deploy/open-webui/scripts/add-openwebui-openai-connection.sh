#!/usr/bin/env bash
# Append (or update) ONE OpenAI-compatible connection in Open WebUI's Postgres config without
# touching the other connections (sync-openwebui-connections-db.sh replaces the whole list).
#
#   add-openwebui-openai-connection.sh <base_url> <prefix_id> [key_env_var]
#   e.g. add-openwebui-openai-connection.sh http://forge-2b:9085/v1 forge-2b-poc FORGE_2B_API_KEY
#
# The bearer is read from the environment variable named by the 3rd arg (default OPENAI_CONNECTION_KEY)
# so it never appears in argv. Open WebUI caches PersistentConfig in-process: restart the container
# afterwards (docker restart forge-open-webui). Granite-only via the host guard.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=open-webui-host-guard.sh
source "$SCRIPT_DIR/open-webui-host-guard.sh"

BASE_URL="${1:?base_url}"
PREFIX_ID="${2:?prefix_id}"
KEY_VAR="${3:-OPENAI_CONNECTION_KEY}"
KEY="${!KEY_VAR:-}"
[[ -n "$KEY" ]] || { echo "env $KEY_VAR is empty" >&2; exit 2; }
PG_CONTAINER="${OPEN_WEBUI_PG_CONTAINER:-forge-open-webui-postgres}"

# psql variables are not expanded inside DO blocks: pass them through session settings instead.
docker exec -i "$PG_CONTAINER" psql -U open_webui -d open_webui -v ON_ERROR_STOP=1 \
  -v url="$BASE_URL" -v key="$KEY" -v prefix="$PREFIX_ID" <<'SQL'
\set QUIET on
\pset tuples_only on
SELECT (set_config('f2b.url', :'url', false) IS NOT NULL) AND (set_config('f2b.key', :'key', false) IS NOT NULL) AND (set_config('f2b.prefix', :'prefix', false) IS NOT NULL) AS bound \g /dev/null
\pset tuples_only off
DO $$
DECLARE
  v_url    text := current_setting('f2b.url');
  v_key    text := current_setting('f2b.key');
  v_prefix text := current_setting('f2b.prefix');
  urls  jsonb := COALESCE((SELECT value::jsonb FROM config WHERE key = 'openai.api_base_urls'), '[]'::jsonb);
  keys  jsonb := COALESCE((SELECT value::jsonb FROM config WHERE key = 'openai.api_keys'), '[]'::jsonb);
  cfgs  jsonb := COALESCE((SELECT value::jsonb FROM config WHERE key = 'openai.api_configs'), '{}'::jsonb);
  idx   int;
  n     int := jsonb_array_length(urls);
  ts    bigint := extract(epoch from now())::bigint;
BEGIN
  SELECT i - 1 INTO idx FROM jsonb_array_elements_text(urls) WITH ORDINALITY AS t(u, i) WHERE u = v_url LIMIT 1;
  IF idx IS NULL THEN
    urls := urls || to_jsonb(v_url);
    keys := keys || to_jsonb(v_key);
    idx := n;
  ELSE
    keys := jsonb_set(keys, ARRAY[idx::text], to_jsonb(v_key));
  END IF;
  cfgs := jsonb_set(cfgs, ARRAY[idx::text], jsonb_build_object('enable', true, 'prefix_id', v_prefix, 'provider', 'openai'), true);
  INSERT INTO config(key, value, updated_at) VALUES ('openai.enable', 'true'::json, ts)
    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = ts;
  INSERT INTO config(key, value, updated_at) VALUES ('openai.api_base_urls', urls::json, ts)
    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = ts;
  INSERT INTO config(key, value, updated_at) VALUES ('openai.api_keys', keys::json, ts)
    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = ts;
  INSERT INTO config(key, value, updated_at) VALUES ('openai.api_configs', cfgs::json, ts)
    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = ts;
  RAISE NOTICE 'connection index % -> % (prefix %)', idx, v_url, v_prefix;
END $$;
SELECT key, CASE WHEN key = 'openai.api_keys' THEN '[redacted]' ELSE value::text END FROM config WHERE key LIKE 'openai.%' ORDER BY key;
SQL
echo "Restart Open WebUI to load: docker restart ${OPEN_WEBUI_CONTAINER:-forge-open-webui}"
