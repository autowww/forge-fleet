#!/usr/bin/env bash
# Deprecated name — calls install-caddy-fleet.sh (system layout, non-interactive, requires root).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export FLEET_BEARER_TOKEN="${FLEET_BEARER_TOKEN:-${1:-}}"
exec sudo -E bash "$SCRIPT_DIR/install-caddy-fleet.sh" --non-interactive --layout system
