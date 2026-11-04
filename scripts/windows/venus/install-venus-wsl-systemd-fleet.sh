#!/usr/bin/env bash
# Run inside Venus Ubuntu WSL as root: system-level forge-fleet (avoids broken user@1000 / Falcon cgroup).
set -euo pipefail
cat >/etc/systemd/system/forge-fleet.service <<'EOF'
[Unit]
Description=Forge Fleet (WSL system unit)
After=network-online.target docker.service
Wants=network-online.target docker.service

[Service]
Type=simple
User=forge
Group=forge
Environment=PYTHONUNBUFFERED=1
Environment=PATH=/snap/bin:/var/lib/snapd/snap/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
WorkingDirectory=/home/forge/.local/share/forge-fleet
EnvironmentFile=-/home/forge/.config/forge-fleet/forge-fleet.env
ExecStart=/usr/bin/python3 -m fleet_server --host 0.0.0.0 --port 18766 --data-dir /home/forge/.local/state/forge-fleet
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable forge-fleet.service
systemctl restart forge-fleet.service
systemctl is-active forge-fleet.service
curl -fsS http://127.0.0.1:18766/v1/health | head -c 200
echo
