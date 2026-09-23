#!/usr/bin/env bash
# Install cloudflared from Cloudflare apt repo (Ubuntu). Idempotent.
set -euo pipefail

if command -v cloudflared >/dev/null 2>&1; then
  echo "install-cloudflared: cloudflared already available"
  exit 0
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "install-cloudflared: apt-get required" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y ca-certificates curl gnupg

install -d /usr/share/keyrings
if [[ ! -f /usr/share/keyrings/cloudflare-main.gpg ]]; then
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
    | gpg --dearmor -o /usr/share/keyrings/cloudflare-main.gpg
fi

CODENAME="$(. /etc/os-release && echo "${VERSION_CODENAME}")"
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared ${CODENAME} main" \
  > /etc/apt/sources.list.d/cloudflared.list

apt-get update -qq
apt-get install -y cloudflared

echo "install-cloudflared: done (run: cloudflared service install <TUNNEL_TOKEN>)"
