#!/usr/bin/env bash
# Install Docker CE from Docker official apt repo (Ubuntu). Idempotent.
set -euo pipefail

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "install-docker-ce: docker already available"
  exit 0
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "install-docker-ce: apt-get required" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y ca-certificates curl gnupg

install -m0755 -d /etc/apt/keyrings
if [[ ! -f /etc/apt/keyrings/docker.asc ]]; then
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
fi

ARCH="$(dpkg --print-architecture)"
CODENAME="$(. /etc/os-release && echo "${VERSION_CODENAME}")"
echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list

apt-get update -qq
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "install-docker-ce: done"
