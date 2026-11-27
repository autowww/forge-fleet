#!/usr/bin/env bash
# Venus fallback when docker pull fails: venv + local artifact store.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/mlflow-host-guard.sh"
mlflow_require_venus_host

ROOT="${FORGE_MLFLOW_STATE:-$HOME/.local/share/forge-mlflow}"
UNIT="$HOME/.config/systemd/user/forge-mlflow.service"
mkdir -p "$ROOT/artifacts" "$HOME/.local/bin" "$(dirname "$UNIT")"
[[ -f "$DEPLOY/.env" ]] || "$SCRIPT_DIR/bootstrap-venus-env.sh"
set -a
# shellcheck disable=SC1091
source "$DEPLOY/.env"
set +a

if ! command -v mlflow >/dev/null 2>&1; then
  python3 -m pip install --user -q 'mlflow==2.14.3'
fi
MLFLOW_BIN="$(command -v mlflow)"

STORE="${FORGE_MLFLOW_BACKEND:-$ROOT/mlflow.db}"
BACKEND="sqlite:///$STORE"
PORT="${MLFLOW_HOST_PORT:-5050}"

cat >"$UNIT" <<EOF
[Unit]
Description=Forge MLflow tracking server (native)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=PYTHONUNBUFFERED=1
WorkingDirectory=$ROOT
ExecStart=$MLFLOW_BIN server --host 127.0.0.1 --port $PORT --backend-store-uri $BACKEND --default-artifact-root mlflow-artifacts:/ --artifacts-destination $ROOT/artifacts --serve-artifacts
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now forge-mlflow.service
echo "MLflow native on http://127.0.0.1:${PORT}/"