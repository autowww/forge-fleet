#!/usr/bin/env bash
# Pack a dedicated Chromium profile from this laptop for Granite (NOT operator daily browser profile).
#
# 1. On laptop, sign in to ChatGPT/Gemini once in a throwaway profile dir, e.g.:
#      google-chrome --user-data-dir=$HOME/.config/chromium-granite-chatgpt-primary ...
# 2. Run: ./pack-open-webui-edge-profile.sh chatgpt-primary
# 3. Upload bundle: ./push-open-webui-edge-profile-via-fleet.sh open-webui-profile-chatgpt-primary.tgz
#
set -euo pipefail

SLUG="${1:?usage: $0 <account-slug>}"
PROFILE_NAME="${2:-chromium-granite-${SLUG}}"
SRC="${HOME}/.config/${PROFILE_NAME}"
OUT="${3:-/tmp/open-webui-profile-${SLUG}.tgz}"

[[ -d "$SRC" ]] || { echo "missing profile dir $SRC" >&2; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bundle/${PROFILE_NAME}"
rsync -a \
  --exclude 'SingletonLock' \
  --exclude 'SingletonCookie' \
  --exclude 'SingletonSocket' \
  --exclude 'Crashpad' \
  --exclude 'ShaderCache' \
  --exclude 'GrShaderCache' \
  --exclude 'GraphiteDawnCache' \
  "$SRC/" "$WORK/bundle/${PROFILE_NAME}/"
cat >"$WORK/.forge_migration_manifest.json" <<'EOF'
{"schema_version":1,"flags":{}}
EOF
cat >"$WORK/bundle/.open-webui-profile.json" <<EOF
{"slug":"${SLUG}","profile_dir":"${PROFILE_NAME}"}
EOF

tar czf "$OUT" -C "$WORK" .forge_migration_manifest.json bundle
echo "wrote $OUT ($(wc -c <"$OUT") bytes)"
echo "sha256=$(sha256sum "$OUT" | awk '{print $1}')"
