#!/usr/bin/env bash
# Assemble signed apt repository tree under dist/apt-publish/fleet/ubuntu/
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEB_DIR="${ROOT}/dist/debs"
OUT="${ROOT}/dist/apt-publish/fleet/ubuntu"
SUITE="${APT_SUITE:-noble}"
KEY_DIR="${ROOT}/packaging/apt/keys"
GPG_HOME="${FORGE_APT_GNUPG_HOME:-${KEY_DIR}/gnupg}"
PUBRING="${GPG_HOME}/pubring.kbx"

die() { echo "build-apt-repo.sh: $*" >&2; exit 1; }

command -v apt-ftparchive >/dev/null || die "apt-ftparchive required (apt-utils)"
command -v gpg >/dev/null || die "gpg required"

[[ -d "$DEB_DIR" ]] || die "run packaging/scripts/build-debs.sh first"

rm -rf "${ROOT}/dist/apt-publish"
mkdir -p "$OUT/pool/main" "$OUT/dists/${SUITE}/main/binary-amd64"

# pool layout (flat component for simplicity)
for deb in "$DEB_DIR"/*.deb; do
  [[ -f "$deb" ]] || continue
  cp -a "$deb" "$OUT/pool/main/"
done

# Packages + Release indices
(
  cd "$OUT"
  apt-ftparchive packages pool/main > "dists/${SUITE}/main/binary-amd64/Packages"
  gzip -9 -k -f "dists/${SUITE}/main/binary-amd64/Packages"
  apt-ftparchive release -o APT::FTPArchive::Release::Origin="Forge Fleet" \
    -o APT::FTPArchive::Release::Label="Forge Fleet" \
    "dists/${SUITE}" > "dists/${SUITE}/Release"
)

# Signing key
if [[ ! -f "$PUBRING" ]] && [[ ! -f "${GPG_HOME}/pubring.gpg" ]]; then
  echo "build-apt-repo.sh: generating dev archive signing key in ${GPG_HOME}"
  mkdir -p "$GPG_HOME"
  chmod 700 "$GPG_HOME"
  gpg --homedir "$GPG_HOME" --batch --passphrase '' --quick-generate-key \
    'Forge Fleet Apt Archive <fleet@forgesdlc.com>' rsa4096 sign 3y
fi

gpg --homedir "$GPG_HOME" --batch --yes --detach-sign --armor \
  -o "$OUT/dists/${SUITE}/Release.gpg" "$OUT/dists/${SUITE}/Release"

gpg --homedir "$GPG_HOME" --batch --yes --clearsign \
  -o "$OUT/dists/${SUITE}/InRelease" "$OUT/dists/${SUITE}/Release"

# Export public key for clients
gpg --homedir "$GPG_HOME" --batch --yes --armor --export \
  >"$OUT/gpg.key"

# install.sh + checksums
install -m0755 "${ROOT}/packaging/ubuntu/install.sh" "$OUT/install.sh"

(
  cd "$OUT"
  sha256sum install.sh pool/main/*.deb > SHA256SUMS
)
gpg --homedir "$GPG_HOME" --batch --yes --detach-sign --armor \
  -o "$OUT/SHA256SUMS.asc" "$OUT/SHA256SUMS"

echo "build-apt-repo.sh: repository ready at ${OUT}"
echo "build-apt-repo.sh: test: deb [signed-by=...] file://${OUT} ${SUITE} main"
