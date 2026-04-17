#!/usr/bin/env bash
# update-fleet.sh — propagate **this dev checkout** to **git** and **local production** (systemd):
#   submodule sync → semver bump → git commit (all changes by default) → git push → sudo install-update.sh
#
# Run from the forge-fleet repo root:
#   ./scripts/update-fleet.sh
#
# **Default (dev propagate):** bumps **patch** version; ``git add -A``; one commit; ``git push`` to ``origin``;
# ``sudo ./install-update.sh`` (rsync → /opt, unit, restart). Use when you type **“update fleet”** in Cursor.
#
# **Strict release:** ``--strict`` — requires a **clean** working tree; only commits ``pyproject.toml`` after bump
# (no other files). Fails if anything is dirty.
#
# Options:
#   --strict       require clean tree; commit only pyproject.toml after bump (release hygiene)
#   --minor        bump minor (0.2.1 → 0.3.0) instead of patch (default: patch)
#   --no-push      commit only, do not push
#   --no-install   skip sudo install-update (no local /opt refresh)
#   --dry-run      print plan only
#   --allow-dirty  (ignored unless --strict) with --strict, allow dirty tree — rarely needed
#   --commit-all   (default in non-strict) no-op kept for compatibility
#   -h, --help

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BUMP_KIND=patch
STRICT=0
NO_PUSH=0
NO_INSTALL=0
ALLOW_DIRTY_STRICT=0
DRY_RUN=0

usage() {
  sed -n '2,/^# Options:/p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --strict) STRICT=1; shift ;;
    --minor) BUMP_KIND=minor; shift ;;
    --patch) BUMP_KIND=patch; shift ;;
    --no-push) NO_PUSH=1; shift ;;
    --no-install) NO_INSTALL=1; shift ;;
    --allow-dirty) ALLOW_DIRTY_STRICT=1; shift ;;
    --commit-all) shift ;; # default in dev mode; kept for scripts that still pass it
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage 0 ;;
    *)
      echo "unknown option: $1" >&2
      usage 2
      ;;
  esac
done

[[ -f "$ROOT/pyproject.toml" ]] || { echo "update-fleet: not a forge-fleet repo: $ROOT" >&2; exit 1; }
[[ -d "$ROOT/fleet_server" ]] || { echo "update-fleet: missing fleet_server/" >&2; exit 1; }

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run] mode=$([[ "$STRICT" -eq 1 ]] && echo strict || echo dev), bump=$BUMP_KIND, push=$([[ "$NO_PUSH" -eq 1 ]] && echo no || echo yes), install=$([[ "$NO_INSTALL" -eq 1 ]] && echo no || echo yes)"
  exit 0
fi

if [[ "$STRICT" -eq 1 ]]; then
  if [[ "$ALLOW_DIRTY_STRICT" -eq 0 ]] && [[ -n "$(git status --porcelain 2>/dev/null || true)" ]]; then
    echo "update-fleet: --strict requires a clean working tree (or pass --allow-dirty)." >&2
    exit 1
  fi
fi

if [[ "$NO_PUSH" -eq 0 ]]; then
  if ! git remote get-url origin >/dev/null 2>&1; then
    echo "update-fleet: git remote 'origin' is not set. Add: git remote add origin <url>" >&2
    exit 1
  fi
fi

echo "[update-fleet] submodule update…"
git submodule update --init --recursive

PY="$ROOT/scripts/bump_pyproject_version.py"
if [[ "$BUMP_KIND" == minor ]]; then
  NEW_VER="$(python3 "$PY" "$ROOT/pyproject.toml" --minor)"
else
  NEW_VER="$(python3 "$PY" "$ROOT/pyproject.toml" --patch)"
fi
echo "[update-fleet] version -> $NEW_VER"

MSG="chore(release): forge-fleet v$NEW_VER"

if [[ "$STRICT" -eq 1 ]]; then
  git add pyproject.toml
else
  git add -A
fi

if git diff --staged --quiet; then
  echo "update-fleet: nothing staged to commit (unexpected after version bump)" >&2
  exit 1
fi

git commit -m "$MSG"

if [[ "$NO_PUSH" -eq 0 ]]; then
  echo "[update-fleet] git push…"
  br="$(git branch --show-current)"
  if git rev-parse --abbrev-ref "@{u}" >/dev/null 2>&1; then
    git push
  else
    git push -u origin "$br"
  fi
else
  echo "[update-fleet] skipped push (--no-push)"
fi

if [[ "$NO_INSTALL" -eq 0 ]]; then
  echo "[update-fleet] install-update.sh (sudo)…"
  sudo env FLEET_SRC="$ROOT" "$ROOT/install-update.sh"
else
  echo "[update-fleet] skipped install-update (--no-install)"
fi

echo "[update-fleet] done (v$NEW_VER)."
