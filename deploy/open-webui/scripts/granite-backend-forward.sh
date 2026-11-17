#!/usr/bin/env bash
# SSH local forwards from Mercury to Granite Open WebUI backends.
set -euo pipefail
REMOTE="${FORGE_OPENWEBUI_GRANITE_SSH:-granite}"
binds=(
  -L 127.0.0.1:18080:127.0.0.1:18080
  -L 127.0.0.1:9240:127.0.0.1:9240
  -L 127.0.0.1:9241:127.0.0.1:9241
)
extra_ips="$(
  {
    docker inspect -f '{{range .NetworkSettings.Networks}}{{.Gateway}} {{end}}' forge-open-webui 2>/dev/null || true
    docker exec forge-open-webui python3 -c 'import socket; print(socket.gethostbyname("host.docker.internal"))' 2>/dev/null || true
  } | tr ' ' '\n' | awk 'NF && $1 != "127.0.0.1"' | sort -u
)"
while IFS= read -r bridge_ip; do
  [[ -n "$bridge_ip" ]] || continue
  ip -4 addr show | grep -q "inet ${bridge_ip}/" || continue
  binds+=(
    -L "${bridge_ip}:18080:127.0.0.1:18080"
    -L "${bridge_ip}:9240:127.0.0.1:9240"
    -L "${bridge_ip}:9241:127.0.0.1:9241"
  )
done <<<"$extra_ips"
exec ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 "${binds[@]}" "$REMOTE"