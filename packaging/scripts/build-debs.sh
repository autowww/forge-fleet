#!/usr/bin/env bash
# Build forge-fleet, forge-fleet-user, and forge-fleet-docker .deb packages.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIST="${ROOT}/dist/debs"
VERSION="$("${ROOT}/packaging/scripts/read-version.sh")"
ARCH="${DEB_ARCH:-amd64}"

die() { echo "build-debs.sh: $*" >&2; exit 1; }

command -v dpkg-deb >/dev/null || die "dpkg-deb not found (install dpkg)"
[[ -d "${ROOT}/fleet_server" ]] || die "missing fleet_server"
[[ -d "${ROOT}/kitchensink" ]] || die "missing kitchensink submodule"

rm -rf "${ROOT}/dist/staging"
mkdir -p "$DIST"

stage_common_code() {
  local dest_lib="$1"
  mkdir -p "$dest_lib"
  rsync -a \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    "${ROOT}/fleet_server/" "$dest_lib/fleet_server/"
  mkdir -p "$dest_lib/systemd"
  install -m0644 "${ROOT}/systemd/environment.example" "$dest_lib/systemd/environment.example"
  bash "${ROOT}/packaging/scripts/bundle-kitchensink-admin.sh" \
    "${ROOT}/kitchensink" "$dest_lib/kitchensink"
}

build_forge_fleet_user() {
  local staging="${ROOT}/dist/staging/forge-fleet-user"
  rm -rf "$staging"
  mkdir -p "$staging/DEBIAN"
  stage_common_code "$staging/usr/lib/forge-fleet"
  mkdir -p "$staging/usr/bin"
  install -m0755 "${ROOT}/scripts/land-fleet" "$staging/usr/bin/land-fleet"

  cat >"$staging/DEBIAN/control" <<EOF
Package: forge-fleet-user
Version: ${VERSION}
Section: admin
Priority: optional
Architecture: ${ARCH}
Depends: python3 (>= 3.11), rsync, curl
Recommends: forge-fleet-docker
Maintainer: Forge Fleet <fleet@forgesdlc.com>
Description: Forge Fleet user cockpit (systemd --user, port 18766)
 HTTP control plane for docker_argv jobs; mesh laptop router role.
EOF

  cat >"$staging/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
  echo "forge-fleet-user: run as your user: land-fleet setup-user"
  echo "forge-fleet-user: then: curl -fsS http://127.0.0.1:18766/v1/health"
fi
EOF
  chmod 0755 "$staging/DEBIAN/postinst"

  cat >"$staging/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
if [ -d /run/systemd/system ] && command -v systemctl >/dev/null 2>&1; then
  for u in /home/*; do
    [ -d "$u" ] || continue
    name=$(basename "$u")
    if [ -f "$u/.config/systemd/user/forge-fleet.service" ]; then
      runuser -u "$name" -- systemctl --user stop forge-fleet.service 2>/dev/null || true
    fi
  done
fi
EOF
  chmod 0755 "$staging/DEBIAN/prerm"

  dpkg-deb --root-owner-group --build "$staging" "${DIST}/forge-fleet-user_${VERSION}_${ARCH}.deb"
}

build_forge_fleet_system() {
  local staging="${ROOT}/dist/staging/forge-fleet"
  rm -rf "$staging"
  mkdir -p "$staging/DEBIAN"
  stage_common_code "$staging/opt/forge-fleet"
  mkdir -p "$staging/lib/systemd/system" "$staging/etc/forge-fleet"
  install -m0644 "${ROOT}/systemd/forge-fleet.service" "$staging/lib/systemd/system/forge-fleet.service"
  install -m0600 "${ROOT}/systemd/environment.example" "$staging/etc/forge-fleet/forge-fleet.env"

  cat >"$staging/DEBIAN/control" <<EOF
Package: forge-fleet
Version: ${VERSION}
Section: admin
Priority: optional
Architecture: ${ARCH}
Depends: python3 (>= 3.11), adduser, rsync, curl
Recommends: forge-fleet-docker
Maintainer: Forge Fleet <fleet@forgesdlc.com>
Description: Forge Fleet system daemon (port 18765)
 HTTP control plane for docker_argv jobs on /opt/forge-fleet.
EOF

  cat >"$staging/DEBIAN/conffiles" <<EOF
/etc/forge-fleet/forge-fleet.env
EOF

  cat >"$staging/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
  if ! id forge-fleet >/dev/null 2>&1; then
    adduser --system --group --home /var/lib/forge-fleet --no-create-home forge-fleet 2>/dev/null || \
      adduser --system --home /var/lib/forge-fleet --no-create-home forge-fleet
  fi
  mkdir -p /var/lib/forge-fleet /etc/forge-fleet
  chown forge-fleet:forge-fleet /var/lib/forge-fleet 2>/dev/null || true
  if [ ! -f /etc/forge-fleet/forge-fleet.env ]; then
    mkdir -p /etc/forge-fleet
    install -m0600 -o root -g root /opt/forge-fleet/systemd/environment.example /etc/forge-fleet/forge-fleet.env
  fi
  if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload
    systemctl enable forge-fleet.service 2>/dev/null || true
    systemctl restart forge-fleet.service 2>/dev/null || systemctl start forge-fleet.service 2>/dev/null || true
  fi
fi
EOF
  chmod 0755 "$staging/DEBIAN/postinst"

  cat >"$staging/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
if command -v systemctl >/dev/null 2>&1; then
  systemctl stop forge-fleet.service 2>/dev/null || true
fi
EOF
  chmod 0755 "$staging/DEBIAN/prerm"

  dpkg-deb --root-owner-group --build "$staging" "${DIST}/forge-fleet_${VERSION}_${ARCH}.deb"
}

build_forge_fleet_docker() {
  local staging="${ROOT}/dist/staging/forge-fleet-docker"
  rm -rf "$staging"
  mkdir -p "$staging/DEBIAN" "$staging/usr/share/forge-fleet-docker"
  install -m0755 "${ROOT}/packaging/scripts/install-docker-ce.sh" "$staging/usr/share/forge-fleet-docker/install-docker-ce.sh"

  cat >"$staging/DEBIAN/control" <<EOF
Package: forge-fleet-docker
Version: ${VERSION}
Section: admin
Priority: optional
Architecture: all
Depends: ca-certificates, curl, gnupg
Maintainer: Forge Fleet <fleet@forgesdlc.com>
Description: Docker CE bootstrap for Forge Fleet hosts
 Adds Docker official apt repository and installs docker-ce, buildx, compose plugins.
EOF

  cat >"$staging/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
  /usr/share/forge-fleet-docker/install-docker-ce.sh
fi
EOF
  chmod 0755 "$staging/DEBIAN/postinst"

  dpkg-deb --root-owner-group --build "$staging" "${DIST}/forge-fleet-docker_${VERSION}_all.deb"
}

build_forge_fleet_user
build_forge_fleet_system
build_forge_fleet_docker

echo "build-debs.sh: wrote ${DIST}/forge-fleet_${VERSION}_${ARCH}.deb"
echo "build-debs.sh: wrote ${DIST}/forge-fleet-user_${VERSION}_${ARCH}.deb"
echo "build-debs.sh: wrote ${DIST}/forge-fleet-docker_${VERSION}_all.deb"
