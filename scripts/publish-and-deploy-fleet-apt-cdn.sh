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

# Resolve the firebase CLI outside a login shell too (systemd-run / cron / Cursor units have no nvm PATH):
# honour FIREBASE_BIN, then PATH, then the newest nvm node install, then a global npm prefix.
FIREBASE_BIN="${FIREBASE_BIN:-}"
if [[ -z "${FIREBASE_BIN}" ]]; then
  if command -v firebase >/dev/null 2>&1; then
    FIREBASE_BIN="$(command -v firebase)"
  else
    for cand in $(ls -1d "${HOME}/.nvm/versions/node/"*/bin/firebase 2>/dev/null | sort -V -r) \
                "${HOME}/.npm-global/bin/firebase" /usr/local/bin/firebase; do
      if [[ -x "${cand}" ]]; then FIREBASE_BIN="${cand}"; break; fi
    done
  fi
fi
if [[ -z "${FIREBASE_BIN}" || ! -x "${FIREBASE_BIN}" ]]; then
  echo "publish-and-deploy-fleet-apt-cdn: firebase CLI not found (PATH, ~/.nvm/versions/node/*/bin, ~/.npm-global/bin); set FIREBASE_BIN=…; staged at ${PKG_SITE}/public/fleet/ubuntu" >&2
  exit 1
fi
export PATH="$(dirname "${FIREBASE_BIN}"):${PATH}"   # firebase-tools needs its sibling `node` on PATH

cd "${PKG_SITE}"
echo "publish-and-deploy-fleet-apt-cdn: firebase deploy --only hosting:${HOSTING_SITE} --project ${FIREBASE_PROJECT}"
if [[ -n "${FIREBASE_TOKEN:-}" ]]; then
  "${FIREBASE_BIN}" deploy --only "hosting:${HOSTING_SITE}" --project "${FIREBASE_PROJECT}" --non-interactive --token "${FIREBASE_TOKEN}"
else
  "${FIREBASE_BIN}" deploy --only "hosting:${HOSTING_SITE}" --project "${FIREBASE_PROJECT}" --non-interactive
fi

echo "publish-and-deploy-fleet-apt-cdn: done — verify Packages index on packages.forgesdlc.com"
