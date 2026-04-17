#!/usr/bin/env bash
# Deprecated name — calls install-caddy-fleet.sh (user layout, non-interactive).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/install-caddy-fleet.sh" --non-interactive --layout user
