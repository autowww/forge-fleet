#!/usr/bin/env bash
# Smoke-test forge-gateway control plane (local or Granite via BASE_URL).
set -euo pipefail

BASE="${FORGE_GATEWAY_BASE:-http://127.0.0.1:${GATEWAY_PORT:-11434}}"
TOKEN="${FORGE_API_TOKEN:-${LLM_API_KEY:-}}"
AUTH=()
if [[ -n "$TOKEN" ]]; then
  AUTH=(-H "Authorization: Bearer ${TOKEN}")
fi

echo "== healthz =="
curl -fsS "${BASE}/healthz" | head -c 200
echo

echo "== classify-mode (task_code) =="
curl -fsS "${AUTH[@]}" -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"def add(a,b): return a+b"}]}' \
  "${BASE}/v1/llm/classify-mode" | head -c 400
echo

echo "== active =="
curl -fsS "${AUTH[@]}" "${BASE}/v1/llm/active" | head -c 400
echo

echo "OK"
