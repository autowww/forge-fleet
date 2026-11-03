#!/usr/bin/env bash
# Copy forge-llm gateway + runner config into forge-fleet deploy bundle.
set -euo pipefail

FLEET_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${FORGE_LLM_SRC:-$FLEET_ROOT/../forge-llm}"
DEST="$FLEET_ROOT/deploy/forge-llm-control-plane"

if [[ ! -d "$SRC/apps/forge-gateway" ]]; then
  echo "sync-forge-llm-control-plane: missing $SRC/apps/forge-gateway" >&2
  exit 1
fi

rsync -a --delete \
  --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' \
  "$SRC/apps/forge-gateway/" "$DEST/apps/forge-gateway/"

mkdir -p "$DEST/configs" "$DEST/scripts"
rsync -a "$SRC/configs/runner.granite.yaml" "$SRC/configs/runner.example.yaml" "$DEST/configs/"
rsync -a "$SRC/scripts/apply-runner-host.sh" "$DEST/scripts/"
chmod +x "$DEST/scripts/apply-runner-host.sh"

echo "synced forge-llm -> $DEST"
