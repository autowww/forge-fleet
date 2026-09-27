#!/usr/bin/env bash
# Build apt repo, stage forge-packages-website, deploy to packages.forgesdlc.com.
# Sole distribution channel for Fleet .deb packages (not git / GitHub Releases).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODE_ROOT="$(cd "${ROOT}/.." && pwd)"
PKG_SITE="${FORGE_PACKAGES_WEBSITE:-${CODE_ROOT}/forge-packages-website}"
FIREBASE_PROJECT="${FORGE_FLEET_APT_FIREBASE_PROJECT:-fleet-2f1d3}"
HOSTING_SITE="${FORGE_FLEET_APT_HOSTING_SITE:-forge-packages}"

bash "${ROOT}/scripts/publish-fleet-apt.sh"

if ! command -v firebase >/dev/null 2>&1; then
  echo "publish-and-deploy-fleet-apt-cdn: firebase CLI not found; staged at ${PKG_SITE}/public/fleet/ubuntu" >&2
  exit 1
fi

cd "${PKG_SITE}"
echo "publish-and-deploy-fleet-apt-cdn: firebase deploy --only hosting:${HOSTING_SITE} --project ${FIREBASE_PROJECT}"
if [[ -n "${FIREBASE_TOKEN:-}" ]]; then
  firebase deploy --only "hosting:${HOSTING_SITE}" --project "${FIREBASE_PROJECT}" --non-interactive --token "${FIREBASE_TOKEN}"
else
  firebase deploy --only "hosting:${HOSTING_SITE}" --project "${FIREBASE_PROJECT}" --non-interactive
fi

echo "publish-and-deploy-fleet-apt-cdn: done — verify Packages index on packages.forgesdlc.com"
