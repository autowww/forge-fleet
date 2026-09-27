#!/usr/bin/env bash
# Build debs + apt repo and copy to forge-packages-website for Firebase deploy.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODE_ROOT="$(cd "${ROOT}/.." && pwd)"
PKG_SITE="${FORGE_PACKAGES_WEBSITE:-${CODE_ROOT}/forge-packages-website}"
DEST="${PKG_SITE}/public/fleet/ubuntu"

bash "${ROOT}/packaging/scripts/build-debs.sh"
bash "${ROOT}/packaging/scripts/build-apt-repo.sh"

rm -rf "$DEST"
mkdir -p "$(dirname "$DEST")"
cp -a "${ROOT}/dist/apt-publish/fleet/ubuntu" "$DEST"

echo "publish-fleet-apt.sh: staged ${DEST}"
echo "publish-fleet-apt.sh: policy — debs live on packages CDN only (not GitHub Releases)."
echo "publish-fleet-apt.sh: deploy with:"
echo "  cd ${PKG_SITE} && firebase login --reauth  # if needed"
echo "  cd ${PKG_SITE} && firebase deploy --only hosting:forge-packages --project fleet-2f1d3"
echo "publish-fleet-apt.sh: see docs/maintainers/05-fleet-apt-cdn-publish.md"
