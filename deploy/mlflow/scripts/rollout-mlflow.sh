#!/usr/bin/env bash
# Venus MLflow compose rollout.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/mlflow-host-guard.sh"
mlflow_require_venus_host

cd "$DEPLOY"
[[ -f .env ]] || { echo "copy .env.example to .env" >&2; exit 1; }
set -a
# shellcheck disable=SC1091
source .env
set +a

docker volume create "${MLFLOW_PGDATA_VOLUME:-forge_mlflow_pgdata}" 2>/dev/null || true
docker volume create "${MLFLOW_ARTIFACTS_VOLUME:-forge_mlflow_artifacts}" 2>/dev/null || true
docker compose -f compose.yaml -f compose.venus.yaml pull
docker compose -f compose.yaml -f compose.venus.yaml up -d --remove-orphans
echo "MLflow loopback: http://127.0.0.1:${MLFLOW_HOST_PORT:-5050}/"