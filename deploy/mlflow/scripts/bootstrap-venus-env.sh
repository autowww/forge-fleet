#!/usr/bin/env bash
# Create deploy/mlflow/.env on Venus when missing.
set -euo pipefail
DEPLOY="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$DEPLOY/.env"
if [[ -f "$ENV_FILE" ]]; then
  echo "$ENV_FILE exists"
  exit 0
fi
pg="$(openssl rand -hex 16)"
track="$(openssl rand -hex 12)"
admin="$(openssl rand -hex 12)"
cp "$DEPLOY/.env.example" "$ENV_FILE"
python3 - "$ENV_FILE" "$pg" "$track" "$admin" <<'PY'
import sys
from pathlib import Path
path, pg, track, admin = sys.argv[1:5]
lines = Path(path).read_text().splitlines()
out = []
for ln in lines:
    if ln.startswith("MLFLOW_POSTGRES_PASSWORD="):
        ln = f"MLFLOW_POSTGRES_PASSWORD={pg}"
    elif ln.startswith("MLFLOW_BACKEND_STORE_URI="):
        ln = f"MLFLOW_BACKEND_STORE_URI=postgresql://mlflow:{pg}@postgres:5432/mlflow"
    elif ln.startswith("MLFLOW_TRACKING_PASSWORD="):
        ln = f"MLFLOW_TRACKING_PASSWORD={track}"
    elif ln.startswith("MLFLOW_ADMIN_PASSWORD="):
        ln = f"MLFLOW_ADMIN_PASSWORD={admin}"
    out.append(ln)
Path(path).write_text("\n".join(out) + "\n")
PY
chmod 600 "$ENV_FILE"
echo "created $ENV_FILE"