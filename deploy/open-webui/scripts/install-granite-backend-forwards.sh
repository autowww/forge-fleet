#!/usr/bin/env bash
# Mercury forwards to Granite Open WebUI backends (forge-gateway + bridges).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT="$HOME/.config/systemd/user/forge-openwebui-granite-forward.service"
mkdir -p "$(dirname "$UNIT")"
chmod +x "$SCRIPT_DIR/granite-backend-forward.sh"
cat >"$UNIT" <<EOF
[Unit]
Description=SSH forwards to Granite LLM Open WebUI backends
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=${SCRIPT_DIR}/granite-backend-forward.sh
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now forge-openwebui-granite-forward.service
systemctl --user restart forge-openwebui-granite-forward.service
echo "Forwards unit installed"