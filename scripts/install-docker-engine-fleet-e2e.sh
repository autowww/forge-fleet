#!/usr/bin/env bash
# Install Docker Engine (Ubuntu/Debian docker.io), wire Forge Fleet to docker.sock,
# switch Fleet off Podman override, restart Fleet, and HTTP smoke + template build E2E.
#
# This script is for a minimal local E2E (docker.io only). Production and template-build hosts
# should follow docs/HOST-BOOTSTRAP.md (Docker CE + docker-buildx-plugin) instead.
#
# Note: Do NOT use SupplementaryGroups=docker on user systemd units — it often fails with
# status=216/GROUP ("Changing group credentials failed: Operation not permitted").
# After usermod -aG docker, your existing systemd --user session may still lack GID docker until
# you log out/in (or restart user@$(id -u).service). Until then, use ExecStart via:
#   /usr/bin/sg docker -c '/usr/bin/python3 -m fleet_server …'
# so Fleet can reach /var/run/docker.sock (see ~/.config/systemd/user/forge-fleet.service).
set -euo pipefail

ENV_FILE="${HOME}/.config/forge-fleet/forge-fleet.env"
UNIT="${HOME}/.config/systemd/user/forge-fleet.service"
BASE="${FLEET_HTTP:-http://127.0.0.1:18766}"

die() { echo "error: $*" >&2; exit 1; }

need_cmd() { command -v "$1" >/dev/null 2>&1 || die "missing command: $1"; }

need_cmd sudo
need_cmd apt-get
need_cmd curl
need_cmd systemctl

echo "==> apt: install docker.io"
sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io

echo "==> systemd: docker daemon"
sudo systemctl enable --now docker

getent group docker >/dev/null || die "docker group missing after package install"

TARGET_USER="${SUDO_USER:-$USER}"
if [[ -z "${TARGET_USER}" || "${TARGET_USER}" == root ]]; then
  TARGET_USER="$(id -un)"
fi

echo "==> account: add ${TARGET_USER} to group docker (docker.sock is root:docker mode 660)"
sudo usermod -aG docker "${TARGET_USER}"

if [[ -f "$UNIT" ]] && grep -q '^SupplementaryGroups=docker' "$UNIT"; then
  echo "==> unit: remove SupplementaryGroups=docker (incompatible with user systemd here)"
  sed -i '/^SupplementaryGroups=docker$/d' "$UNIT"
fi

if [[ -f "$ENV_FILE" ]] && grep -q '^FLEET_DOCKER_BIN=' "$ENV_FILE"; then
  echo "==> env: remove FLEET_DOCKER_BIN (use Docker CLI on PATH)"
  sed -i '/^FLEET_DOCKER_BIN=/d' "$ENV_FILE"
fi

systemctl --user daemon-reload

IN_DOCKER=0
if id -nG "${TARGET_USER}" | tr ' ' '\n' | grep -qx docker; then
  IN_DOCKER=1
fi

if [[ "${IN_DOCKER}" -eq 0 ]]; then
  echo ""
  echo "IMPORTANT: group membership becomes visible after a NEW login session."
  echo "  Log out and back in (or reboot), then run:"
  echo "    systemctl --user restart forge-fleet.service"
  echo "  Then verify: docker pull alpine:3.19"
  echo ""
fi

systemctl --user restart forge-fleet.service
sleep 1

if ! systemctl --user is-active forge-fleet.service >/dev/null; then
  journalctl --user -u forge-fleet.service -n 40 --no-pager
  die "forge-fleet.service failed to start"
fi

if [[ "${IN_DOCKER}" -eq 0 ]]; then
  echo "==> WARNING: current shell may not be in group docker yet — template build may fail until re-login."
fi

echo "==> health"
curl -fsS "$BASE/v1/health" | head -c 300
echo ""

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a && . "$ENV_FILE" && set +a
fi
AUTH=()
if [[ -n "${FLEET_BEARER_TOKEN:-}" ]]; then
  AUTH=(-H "Authorization: Bearer ${FLEET_BEARER_TOKEN}")
fi

echo "==> GET /v1/container-types"
curl -fsS "${AUTH[@]}" "$BASE/v1/container-types" | head -c 200
echo ""

echo "==> GET /v1/container-templates"
curl -fsS "${AUTH[@]}" "$BASE/v1/container-templates" | head -c 400
echo ""

echo "==> PUT alpine template (idempotent)"
curl -fsS -X PUT "${AUTH[@]}" -H "Content-Type: application/json" \
  -d '{"version":1,"templates":[{"id":"alpine_3_19","title":"Alpine 3.19","kind":"image","ref":"alpine:3.19","notes":"E2E"}]}' \
  "$BASE/v1/container-templates" | head -c 400
echo ""

echo "==> POST /v1/container-templates/build"
set +e
curl -fsS -X POST "${AUTH[@]}" -H "Content-Type: application/json" \
  -d '{"requirement_ids":["alpine_3_19"]}' \
  "$BASE/v1/container-templates/build"
BUILD_EXIT=$?
set -e
echo ""

if [[ "${BUILD_EXIT}" -ne 0 ]] && [[ "${IN_DOCKER}" -eq 0 ]]; then
  echo "(Build failed — after re-login run: curl -fsS -X POST .../container-templates/build ...)"
fi

echo "==> GET resolve (cache hit, no build)"
curl -fsS "${AUTH[@]}" \
  "$BASE/v1/container-templates/resolve?requirements=alpine_3_19&build_if_missing=0" || true
echo ""

echo "OK: Docker + Fleet E2E script finished."
