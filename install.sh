#!/usr/bin/env bash
# Deprecated alias: use install-update.sh
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/install-update.sh" "$@"
