#!/usr/bin/env bash
# Mercury loopback forwards to Granite Open WebUI backends (forge-gateway + bridges).
set -euo pipefail
REMOTE="${FORGE_OPENWEBUI_GRANITE_SSH:-granite}"
UNIT="$HOME/.config/systemd/user/forge-openwebui-granite-forward.service"
mkdir -p "$(dirname "$UNIT")"
cat >"$UNIT" <<EOF
[Unit]
Description=SSH forwards to Granite LLM Open WebUI backends
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -L 127.0.0.1:18080:127.0.0.1:18080 \
  -L 127.0.0.1:9240:127.0.0.1:9240 \
  -L 127.0.0.1:9241:127.0.0.1:9241 \
  ${REMOTE}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now forge-openwebui-granite-forward.service
echo "Forwards active on 127.0.0.1:18080,9240,9241"