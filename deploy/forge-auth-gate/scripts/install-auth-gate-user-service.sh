#!/usr/bin/env bash
# Install systemd user unit for forge-auth-gate (Mercury / Venus loopback).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_DST="${FORGE_AUTH_GATE_ENV:-$HOME/.config/forge-auth-gate/gate.env}"
UNIT_DST="$HOME/.config/systemd/user/forge-auth-gate.service"
mkdir -p "$(dirname "$ENV_DST")" "$HOME/.config/systemd/user"
if [[ ! -f "$ENV_DST" ]]; then
  cp "$ROOT/forge-auth-gate.env.example" "$ENV_DST"
  chmod 600 "$ENV_DST"
  echo "Created $ENV_DST — set FORGE_AUTH_GATE_SECRET and mode-specific values."
fi
sed "s|/home/forge|$HOME|g" "$ROOT/systemd/forge-auth-gate.service" >"$UNIT_DST"
systemctl --user daemon-reload
systemctl --user enable forge-auth-gate.service
echo "Installed $UNIT_DST — systemctl --user restart forge-auth-gate.service"