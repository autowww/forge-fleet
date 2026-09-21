#!/usr/bin/env bash
# Dev gate (5a-bis): bounded market bar ingest smoke on market-studio-dev.
set -euo pipefail

# Thin-client studio on the operator machine (FORGE_MARKET_REMOTE_API → market-studio-dev).
BASE="${FORGE_MARKET_DEV_GATE_URL:-http://127.0.0.1:${FORGE_MARKET_DEV_PORT:-9795}}"

echo "POST mock harvest on dev studio (laptop-edge; bars upload to Granite after fetch)"
job="$(curl -fsS -X POST "${BASE}/api/prices/sync" \
  -H "Content-Type: application/json" \
  -d '{"tickers":["AAPL"],"source":"orchestrated","interval":"1d","lookback_bars":5,"mock":true,"prepare_cdp":false}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin).get("job_id",""))')"
[[ -n "$job" ]] || { echo "no job_id returned"; exit 1; }
echo "job_id=$job"

for _ in $(seq 1 60); do
  sleep 5
  st="$(curl -fsS "${BASE}/api/prices/jobs/${job}" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("job",{}).get("status",""))')"
  echo "status=$st"
  [[ "$st" == "done" || "$st" == "failed" || "$st" == "cancelled" ]] && break
done

[[ "$st" == "done" ]] || { echo "ingest smoke failed: status=$st"; exit 1; }
echo "dev ingest smoke ok"
