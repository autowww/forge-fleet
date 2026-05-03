#!/usr/bin/env bash
# Merge FLEET_GIT_ROOT into forge-fleet.env when the install source is a git checkout.
# Invoked by install-update.sh / install-user.sh after syncing (rsync excludes .git).
#
# Usage: set-fleet-git-root-in-env.sh <env-file> <checkout-dir>
set -euo pipefail

ENV_FILE="${1:?env file required}"
CHECKOUT="${2:?checkout dir required}"

if [[ ! -d "$CHECKOUT/.git" ]]; then
  exit 0
fi

ABS="$(cd "$CHECKOUT" && pwd)"
mkdir -p "$(dirname "$ENV_FILE")"
[[ -f "$ENV_FILE" ]] || touch "$ENV_FILE"

TMP="$(mktemp "${TMPDIR:-/tmp}/fleet-env-git-root.XXXXXX")"
if grep -q '^[[:space:]]*FLEET_GIT_ROOT=' "$ENV_FILE" 2>/dev/null; then
  grep -v '^[[:space:]]*FLEET_GIT_ROOT=' "$ENV_FILE" >"$TMP" || true
  mv "$TMP" "$ENV_FILE"
else
  rm -f "$TMP"
fi

echo "FLEET_GIT_ROOT=$ABS" >>"$ENV_FILE"
chmod 0600 "$ENV_FILE"
echo "[fleet-install] FLEET_GIT_ROOT -> $ABS (for POST /v1/admin/git-self-update)"
