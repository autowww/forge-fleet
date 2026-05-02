#!/usr/bin/env bash
# Playwright webServer: disposable Fleet data dir + loopback (no bearer required).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
rm -rf .fleet-e2e-data
mkdir -p .fleet-e2e-data
export FLEET_DATA_DIR="$ROOT/.fleet-e2e-data"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
else
  PY="${PYTHON:-python3}"
fi
exec "$PY" -m fleet_server.main --host 127.0.0.1 --port 19876
