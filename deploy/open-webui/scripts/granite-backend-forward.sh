#!/usr/bin/env bash
# SSH local forwards from Mercury to Granite Open WebUI backends.
set -euo pipefail
REMOTE="${FORGE_OPENWEBUI_GRANITE_SSH:-granite}"
# ChatGPT can run on Mercury itself (FORGE_OPENWEBUI_FORWARD_CHATGPT=0). Gemini and the
# Forge LLM gateway stay forwarded until those browsers move too.
ports=(18080)
if [[ "${FORGE_OPENWEBUI_FORWARD_CHATGPT:-1}" != "0" ]]; then
  ports+=(9240)
fi
if [[ "${FORGE_OPENWEBUI_FORWARD_GEMINI:-1}" != "0" ]]; then
  ports+=(9241)
fi
binds=()
for port in "${ports[@]}"; do
  binds+=(-L "127.0.0.1:${port}:127.0.0.1:${port}")
done
extra_ips="$(
  {
    docker inspect -f '{{range .NetworkSettings.Networks}}{{.Gateway}} {{end}}' forge-open-webui 2>/dev/null || true
    docker exec forge-open-webui python3 -c 'import socket; print(socket.gethostbyname("host.docker.internal"))' 2>/dev/null || true
  } | tr ' ' '\n' | awk 'NF && $1 != "127.0.0.1"' | sort -u
)"
while IFS= read -r bridge_ip; do
  [[ -n "$bridge_ip" ]] || continue
  ip -4 addr show | grep -q "inet ${bridge_ip}/" || continue
  for port in "${ports[@]}"; do
    binds+=(-L "${bridge_ip}:${port}:127.0.0.1:${port}")
  done
done <<<"$extra_ips"
exec ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 "${binds[@]}" "$REMOTE"