#!/usr/bin/env bash
# Publish mlx.forgedc.net on the Mercury tunnel. The public port is the auth gate, not the app.
# Mercury gate listens on 127.0.0.1:9795 because 9794 is Forge Atlas.
#
# Usage (from forge-fleet/):
#   export CLOUDFLARE_API_TOKEN=…
#   deploy/mlflow/scripts/apply-cf-mlx-tunnel.sh [--dry-run]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export CF_HOSTNAME="${CF_HOSTNAME:-mlx.forgedc.net}"
export CF_ORIGIN_SERVICE="${CF_ORIGIN_SERVICE:-http://127.0.0.1:9795}"
export CF_TUNNEL_ID="${CF_TUNNEL_ID:-6e783b10-a38e-4715-a57e-f55c649fcba2}"
exec "$SCRIPT_DIR/apply-cf-mlflow-tunnel.sh" "$@"
