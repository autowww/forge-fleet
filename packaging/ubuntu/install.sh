#!/usr/bin/env bash
# Bootstrap Forge Fleet apt repository on Ubuntu (noble).
# Usage: install.sh [--user|--system] [--with-docker]
set -euo pipefail

APT_BASE="${FORGE_APT_BASE_URL:-https://packages.forgesdlc.com/fleet/ubuntu}"
SUITE="${FORGE_APT_SUITE:-noble}"
MODE="user"
WITH_DOCKER=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user) MODE=user; shift ;;
    --system) MODE=system; shift ;;
    --with-docker) WITH_DOCKER=1; shift ;;
    -h|--help)
      echo "Usage: $0 [--user|--system] [--with-docker]"
      exit 0
      ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ "$(id -u)" -ne 0 ]] && [[ "$MODE" == system ]]; then
  echo "install.sh: --system requires root (use sudo)" >&2
  exit 1
fi

SUDO=()
[[ "$(id -u)" -eq 0 ]] || SUDO=(sudo)

KEYRING="/usr/share/keyrings/forge-fleet-archive-keyring.gpg"
SOURCES="/etc/apt/sources.list.d/forge-fleet.list"

"${SUDO[@]}" install -d /usr/share/keyrings
curl -fsSL "${APT_BASE}/gpg.key" | "${SUDO[@]}" gpg --dearmor -o "$KEYRING"
chmod a+r "$KEYRING" 2>/dev/null || "${SUDO[@]}" chmod a+r "$KEYRING"

echo "deb [signed-by=${KEYRING} arch=amd64] ${APT_BASE} ${SUITE} main" | "${SUDO[@]}" tee "$SOURCES" >/dev/null

if [[ "${FLEET_VERIFY_CHECKSUMS:-0}" == "1" ]]; then
  tmp="$(mktemp -d)"
  curl -fsSL "${APT_BASE}/SHA256SUMS" -o "$tmp/SHA256SUMS"
  curl -fsSL "${APT_BASE}/SHA256SUMS.asc" -o "$tmp/SHA256SUMS.asc"
  gpg --verify "$tmp/SHA256SUMS.asc" "$tmp/SHA256SUMS"
  rm -rf "$tmp"
fi

"${SUDO[@]}" apt-get update -qq
PKGS=(forge-fleet-user)
[[ "$MODE" == system ]] && PKGS=(forge-fleet)
[[ "$WITH_DOCKER" -eq 1 ]] && PKGS+=("forge-fleet-docker")

"${SUDO[@]}" apt-get install -y "${PKGS[@]}"

if [[ "$MODE" == user ]]; then
  if command -v loginctl >/dev/null 2>&1; then
    loginctl enable-linger "${SUDO_USER:-$USER}" 2>/dev/null || \
      "${SUDO[@]}" loginctl enable-linger "${SUDO_USER:-$USER}" 2>/dev/null || true
  fi
  echo "install.sh: run: land-fleet setup-user"
  echo "install.sh: then: land-fleet bootstrap-deps"
  echo "install.sh: health: curl -fsS http://127.0.0.1:18766/v1/health"
else
  echo "install.sh: run: land-fleet bootstrap-deps --server"
  echo "install.sh: health: curl -fsS http://127.0.0.1:18765/v1/health"
fi
