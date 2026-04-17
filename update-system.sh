#!/usr/bin/env bash
# update-system.sh — same as install-update.sh (rsync to /opt, refresh system unit, restart).

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "[update-system] refreshing system install (see install-update.sh for options)"
exec "$ROOT/install-update.sh" "$@"
