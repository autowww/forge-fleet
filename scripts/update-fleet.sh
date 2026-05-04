#!/usr/bin/env bash
# update-fleet.sh — propagate **this dev checkout** to **git** and **local production** (systemd):
#   submodule sync → semver bump → git commit (all changes by default) → git push → optional POST
#   /v1/admin/git-self-update on remote Fleet (--remote-git-self-update) → sudo install-update.sh
#   (sudo failure is non-fatal) → update-user.sh when ~/.config/systemd/user/forge-fleet.service exists (no sudo)
#
# Run from the forge-fleet repo root:
#   ./scripts/update-fleet.sh
#
# **Default (dev propagate):** bumps **patch** version; ``git add -A``; one commit; ``git push`` to ``origin``;
# ``sudo ./install-update.sh`` (rsync → /opt, unit, restart). Use when you type **“update fleet”** in Cursor.
#
# **Host operators:** If a release needs OS-level changes (apt, env vars), add ``### Host operator`` under that
# version in ``CHANGELOG.md`` and an entry in ``docs/host-operator-steps.json`` (see maintainer footer there).
#
# **Strict release:** ``--strict`` — requires a **clean** working tree; only commits ``pyproject.toml`` after bump
# (no other files). Fails if anything is dirty.
#
# Options:
#   --strict       require clean tree; commit only pyproject.toml after bump (release hygiene)
#   --minor        bump minor (0.2.1 → 0.3.0) instead of patch (default: patch)
#   --no-push      commit only, do not push
#   --no-install   skip sudo install-update (no local /opt refresh)
#   --no-user      skip update-user.sh even when a user systemd unit is present
#   --remote-git-self-update  after a successful git push, POST /v1/admin/git-self-update on remote Fleet
#   --remote-url URL   override base URL (else FLEET_REMOTE_GIT_SELF_UPDATE_URL or FORGE_FLEET_BASE_URL)
#   --remote-bearer T  override bearer token (else FORGE_FLEET_BEARER_TOKEN)
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
NO_USER=0
ALLOW_DIRTY_STRICT=0
DRY_RUN=0
REMOTE_GIT_SELF_UPDATE=0
REMOTE_URL_OVERRIDE=""
REMOTE_BEARER_OVERRIDE=""

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
    --no-user) NO_USER=1; shift ;;
    --allow-dirty) ALLOW_DIRTY_STRICT=1; shift ;;
    --commit-all) shift ;; # default in dev mode; kept for scripts that still pass it
    --dry-run) DRY_RUN=1; shift ;;
    --remote-git-self-update) REMOTE_GIT_SELF_UPDATE=1; shift ;;
    --remote-url)
      REMOTE_URL_OVERRIDE="${2:-}"
      if [[ -z "$REMOTE_URL_OVERRIDE" ]]; then echo "update-fleet: --remote-url requires a value" >&2; exit 2; fi
      shift 2
      ;;
    --remote-bearer)
      REMOTE_BEARER_OVERRIDE="${2:-}"
      if [[ -z "$REMOTE_BEARER_OVERRIDE" ]]; then echo "update-fleet: --remote-bearer requires a value" >&2; exit 2; fi
      shift 2
      ;;
    -h|--help) usage 0 ;;
    *)
      echo "unknown option: $1" >&2
      usage 2
      ;;
  esac
done

[[ -f "$ROOT/pyproject.toml" ]] || { echo "update-fleet: not a forge-fleet repo: $ROOT" >&2; exit 1; }
[[ -d "$ROOT/fleet_server" ]] || { echo "update-fleet: missing fleet_server/" >&2; exit 1; }

remote_git_self_update_resolve() {
  _rb_base="${REMOTE_URL_OVERRIDE:-${FLEET_REMOTE_GIT_SELF_UPDATE_URL:-${FORGE_FLEET_BASE_URL:-}}}"
  _rb_base="${_rb_base%/}"
  _rb_bearer="${REMOTE_BEARER_OVERRIDE:-${FORGE_FLEET_BEARER_TOKEN:-}}"
}

invoke_remote_git_self_update() {
  remote_git_self_update_resolve
  if [[ -z "$_rb_base" ]]; then
    echo "update-fleet: --remote-git-self-update requires FORGE_FLEET_BASE_URL or FLEET_REMOTE_GIT_SELF_UPDATE_URL or --remote-url" >&2
    return 1
  fi
  if [[ -z "$_rb_bearer" ]]; then
    echo "update-fleet: --remote-git-self-update requires FORGE_FLEET_BEARER_TOKEN or --remote-bearer" >&2
    return 1
  fi
  _rb_url="${_rb_base}/v1/admin/git-self-update"
  echo "[update-fleet] remote git-self-update POST ${_rb_url}"
  _rb_tmp="$(mktemp)"
  _rb_code="$(curl -sS -o "$_rb_tmp" -w "%{http_code}" -X POST "$_rb_url" \
    -H "Authorization: Bearer ${_rb_bearer}" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -d '{}')"
  if [[ "$_rb_code" != "200" && "$_rb_code" != "400" ]]; then
    echo "update-fleet: remote git-self-update HTTP ${_rb_code}" >&2
    cat "$_rb_tmp" >&2 || true
    rm -f "$_rb_tmp"
    return 1
  fi
  export _UPDATE_FLEET_JSON_TMP="$_rb_tmp"
  if ! python3 -c '
import json, os, pathlib, sys
path = pathlib.Path(os.environ["_UPDATE_FLEET_JSON_TMP"])
j = json.load(path.open(encoding="utf-8"))
ok = j.get("ok")
if ok is True:
    note = (j.get("note") or "").strip() or "git-self-update completed"
    print("[update-fleet] remote ok:", note)
    sys.exit(0)
err = j.get("error") or "unknown"
detail = (j.get("detail") or "").strip()
print("[update-fleet] remote error:", err, file=sys.stderr)
if detail:
    print(detail, file=sys.stderr)
cmd = j.get("system_root_install_command")
if cmd:
    print("[update-fleet] remote system install (run on Fleet host as root):", file=sys.stderr)
    print(cmd, file=sys.stderr)
sys.exit(1)
'; then
    unset _UPDATE_FLEET_JSON_TMP || true
    rm -f "$_rb_tmp"
    return 1
  fi
  unset _UPDATE_FLEET_JSON_TMP || true
  rm -f "$_rb_tmp"
  return 0
}

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run] mode=$([[ "$STRICT" -eq 1 ]] && echo strict || echo dev), bump=$BUMP_KIND, push=$([[ "$NO_PUSH" -eq 1 ]] && echo no || echo yes), install=$([[ "$NO_INSTALL" -eq 1 ]] && echo no || echo yes), user=$([[ "$NO_USER" -eq 1 ]] && echo no || echo yes), remote_git_self_update=$([[ "$REMOTE_GIT_SELF_UPDATE" -eq 1 ]] && echo yes || echo no)"
  if [[ "$REMOTE_GIT_SELF_UPDATE" -eq 1 ]]; then
    remote_git_self_update_resolve
    if [[ -z "$_rb_base" || -z "$_rb_bearer" ]]; then
      echo "[dry-run] would need FORGE_FLEET_BASE_URL (or FLEET_REMOTE_GIT_SELF_UPDATE_URL / --remote-url) and FORGE_FLEET_BEARER_TOKEN (or --remote-bearer)" >&2
    else
      echo "[dry-run] after successful push would: curl -sS -X POST ${_rb_base%/}/v1/admin/git-self-update -H \"Authorization: Bearer ***\" -H Content-Type: application/json -d {}"
    fi
    if [[ "$NO_PUSH" -eq 1 ]]; then
      echo "[dry-run] note: --no-push skips remote step (nothing new on origin for remote to pull)" >&2
    fi
  fi
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

if [[ "$REMOTE_GIT_SELF_UPDATE" -eq 1 ]] && [[ "$NO_PUSH" -eq 0 ]]; then
  invoke_remote_git_self_update || exit 1
elif [[ "$REMOTE_GIT_SELF_UPDATE" -eq 1 ]] && [[ "$NO_PUSH" -eq 1 ]]; then
  echo "[update-fleet] skipped remote git-self-update (--no-push)"
fi

if [[ "$NO_INSTALL" -eq 0 ]]; then
  echo "[update-fleet] install-update.sh (sudo)…"
  if ! sudo env FLEET_SRC="$ROOT" "$ROOT/install-update.sh"; then
    echo "[update-fleet] warning: install-update.sh failed (no TTY/sudo, wrong password, or not system install)." >&2
    echo "[update-fleet] hint: user installs still refresh below via update-user.sh when a user unit exists; or run: ./scripts/update-fleet.sh --no-install" >&2
  fi
else
  echo "[update-fleet] skipped install-update (--no-install)"
fi

if [[ "$NO_USER" -eq 0 ]]; then
  _fleet_user_unit="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/forge-fleet.service"
  if [[ -f "$_fleet_user_unit" ]] && command -v systemctl >/dev/null 2>&1; then
    echo "[update-fleet] update-user.sh (rsync + systemd --user restart)…"
    if ! env FLEET_SRC="$ROOT" "$ROOT/update-user.sh"; then
      echo "[update-fleet] warning: update-user.sh failed (git push already completed)." >&2
    fi
  else
    echo "[update-fleet] skip user install (no $_fleet_user_unit or systemctl missing)"
  fi
else
  echo "[update-fleet] skipped update-user (--no-user)"
fi

echo "[update-fleet] done (v$NEW_VER)."
