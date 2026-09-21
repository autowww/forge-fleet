#!/usr/bin/env bash
# Copy kitchensink CSS/JS required by /admin/ into a package staging tree.
set -euo pipefail

SRC_KS="${1:?kitchensink source dir}"
DEST="${2:?dest dir (e.g. staging/usr/lib/forge-fleet/kitchensink)}"

mkdir -p "$DEST/css" "$DEST/js"
for f in forge-theme.css forge-fleet-admin.css; do
  install -m0644 "$SRC_KS/css/$f" "$DEST/css/$f"
done
for f in forge-theme.js forge-fleet-app-ui.js; do
  install -m0644 "$SRC_KS/js/$f" "$DEST/js/$f"
done
