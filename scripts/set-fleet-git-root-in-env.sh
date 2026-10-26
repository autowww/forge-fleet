#!/usr/bin/env bash
# Merge FLEET_GIT_ROOT + FLEET_GIT_SHA into forge-fleet.env when the install source is a git checkout.
# Invoked by install-update.sh / install-user.sh after syncing (rsync excludes .git).
#
# Usage: set-fleet-git-root-in-env.sh <env-file> <checkout-dir>
set -euo pipefail

ENV_FILE="${1:?env file required}"
CHECKOUT="${2:?checkout dir required}"

if [[ ! -e "$CHECKOUT/.git" ]]; then
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

TMP="$(mktemp "${TMPDIR:-/tmp}/fleet-env-git-sha.XXXXXX")"
if grep -q '^[[:space:]]*FLEET_GIT_SHA=' "$ENV_FILE" 2>/dev/null; then
  grep -v '^[[:space:]]*FLEET_GIT_SHA=' "$ENV_FILE" >"$TMP" || true
  mv "$TMP" "$ENV_FILE"
else
  rm -f "$TMP"
fi

SHA_OUT="$(git -C "$ABS" rev-parse --short HEAD 2>/dev/null || true)"
PYPROJECT="$ABS/pyproject.toml"
SEMVER=""
if [[ -f "$PYPROJECT" ]]; then
  SEMVER="$(grep -E '^[[:space:]]*version[[:space:]]*=' "$PYPROJECT" | head -1 | sed -E 's/^[[:space:]]*version[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/')"
fi
if [[ -n "$SEMVER" ]]; then
  TMP="$(mktemp "${TMPDIR:-/tmp}/fleet-env-semver.XXXXXX")"
  if grep -q '^[[:space:]]*FLEET_PACKAGE_SEMVER=' "$ENV_FILE" 2>/dev/null; then
    grep -v '^[[:space:]]*FLEET_PACKAGE_SEMVER=' "$ENV_FILE" >"$TMP" || true
    mv "$TMP" "$ENV_FILE"
  else
    rm -f "$TMP"
  fi
  echo "FLEET_PACKAGE_SEMVER=$SEMVER" >>"$ENV_FILE"
  echo "[fleet-install] FLEET_PACKAGE_SEMVER -> $SEMVER (from pyproject.toml)"
fi
echo "FLEET_GIT_ROOT=$ABS" >>"$ENV_FILE"
if [[ -n "$SHA_OUT" ]]; then
  echo "FLEET_GIT_SHA=$SHA_OUT" >>"$ENV_FILE"
  echo "[fleet-install] FLEET_GIT_SHA -> $SHA_OUT (admin /v1/version + GitHub drift row)"
fi
chmod 0600 "$ENV_FILE"
echo "[fleet-install] FLEET_GIT_ROOT -> $ABS (for POST /v1/admin/git-self-update)"
