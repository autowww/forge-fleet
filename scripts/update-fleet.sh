#!/usr/bin/env bash
# update-fleet.sh — propagate **this dev checkout** to **git** and **local production** (systemd):
#   submodule sync → semver bump → git commit (all changes by default) → git push → optional POST
#   POST /v1/admin/upgrade on remote Fleet (--remote-upgrade) → apt package only (requires --publish-apt-cdn)
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
#   --remote-upgrade          after push + apt CDN publish, POST /v1/admin/upgrade (apt when the host is on apt;
#                             hosts still on a git channel fall back to the cooperative git upgrade via the same
#                             API — no operator action, no SSH; 409 upgrade_blocked retries once with
#                             on_timeout=force; then polls /v1/health until the new version is reported)
#   --remote-strict-apt       disable the git-channel fallback (fail with migrate_to_apt_required instead)
#   --remote-git-self-update  deprecated alias for --remote-upgrade
#   env: FLEET_REMOTE_UPGRADE_MAX_WAIT_SEC=120  FLEET_REMOTE_UPGRADE_FORCE_ON_BLOCK=1  FLEET_REMOTE_UPGRADE_VERIFY_SEC=180
#   --publish-apt-cdn         after push, build debs and deploy packages.forgesdlc.com (CDN only; not GitHub)
#   --remote-url URL   override base URL (else FLEET_REMOTE_GIT_SELF_UPDATE_URL or FORGE_FLEET_BASE_URL)
#   --remote-bearer T  override bearer token (else FORGE_FLEET_BEARER_TOKEN)
#   --dry-run      print plan only
#   --allow-dirty  (ignored unless --strict) with --strict, allow dirty tree — rarely needed
#   --commit-all   (default in non-strict) no-op kept for compatibility
#   -h, --help

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../scripts/lib/forge-script-help-json.sh
source "$ROOT/../scripts/lib/forge-script-help-json.sh"
cd "$ROOT"

BUMP_KIND=patch
STRICT=0
NO_PUSH=0
NO_INSTALL=0
NO_USER=0
ALLOW_DIRTY_STRICT=0
DRY_RUN=0
REMOTE_UPGRADE=0
REMOTE_STRICT_APT="${FLEET_REMOTE_UPGRADE_STRICT_APT:-0}"
PUBLISH_APT_CDN=0
REMOTE_URL_OVERRIDE=""
REMOTE_BEARER_OVERRIDE=""

usage() {
  sed -n '2,/^# Options:/p' "$0" | sed 's/^# \{0,1\}//' >&2
  forge_help_json_footer "./scripts/update-fleet.sh"
  exit "${1:-0}"
}

forge_help_json() {
  forge_help_json_emit "$(cat <<'EOF'
{
  "schema_version": 1,
  "id": "update-fleet",
  "title": "Update Fleet",
  "description": "Propagate dev checkout to git and local production (submodule sync, semver bump, push, install).",
  "cwd": "forge-fleet",
  "argv0": "scripts/update-fleet.sh",
  "destructive": true,
  "options": [
    {
      "type": "enum",
      "id": "bump_patch",
      "group": "bump",
      "label": "Patch bump (default)",
      "values": [
        {"value": "patch", "label": "Patch"}
      ]
    },
    {
      "type": "enum",
      "id": "bump_minor",
      "group": "bump",
      "flag": "--minor",
      "label": "Minor bump",
      "values": [
        {"value": "minor", "label": "Minor"}
      ]
    },
    {
      "type": "boolean",
      "id": "dry_run",
      "flag": "--dry-run",
      "label": "Print plan only",
      "default": false
    },
    {
      "type": "boolean",
      "id": "no_push",
      "flag": "--no-push",
      "label": "Commit only, do not push",
      "default": false
    },
    {
      "type": "boolean",
      "id": "no_install",
      "flag": "--no-install",
      "label": "Skip sudo install-update (no local /opt refresh)",
      "default": false
    },
    {
      "type": "boolean",
      "id": "remote_upgrade",
      "flag": "--remote-upgrade",
      "label": "POST remote apt upgrade after push (requires --publish-apt-cdn)",
      "default": false
    },
    {
      "type": "boolean",
      "id": "remote_strict_apt",
      "flag": "--remote-strict-apt",
      "label": "Fail on git-channel hosts instead of cooperative git fallback",
      "default": false
    }
  ],
  "presets": [
    {"label": "Dry run", "args": ["--dry-run"]}
  ]
}
EOF
)"
  exit 0
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
    --remote-upgrade) REMOTE_UPGRADE=1; shift ;;
    --remote-strict-apt) REMOTE_STRICT_APT=1; shift ;;
    --remote-git-self-update)
      echo "[update-fleet] warning: --remote-git-self-update is deprecated; use --remote-upgrade --publish-apt-cdn" >&2
      REMOTE_UPGRADE=1
      shift
      ;;
    --publish-apt-cdn) PUBLISH_APT_CDN=1; shift ;;
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
    --help-json) forge_help_json ;;
    -h|--help) usage 0 ;;
    *)
      echo "unknown option: $1" >&2
      usage 2
      ;;
  esac
done

[[ -f "$ROOT/pyproject.toml" ]] || { echo "update-fleet: not a forge-fleet repo: $ROOT" >&2; exit 1; }
[[ -d "$ROOT/fleet_server" ]] || { echo "update-fleet: missing fleet_server/" >&2; exit 1; }

remote_upgrade_resolve() {
  _rb_base="${REMOTE_URL_OVERRIDE:-${FLEET_REMOTE_UPGRADE_URL:-${FLEET_REMOTE_GIT_SELF_UPDATE_URL:-${FORGE_FLEET_BASE_URL:-}}}}"
  _rb_base="${_rb_base%/}"
  _rb_bearer="${REMOTE_BEARER_OVERRIDE:-${FORGE_FLEET_BEARER_TOKEN:-}}"
}

invoke_remote_upgrade() {
  if [[ "$PUBLISH_APT_CDN" -ne 1 ]]; then
    echo "update-fleet: --remote-upgrade requires --publish-apt-cdn (remote hosts use apt packages only, never git pull)" >&2
    return 1
  fi
  remote_upgrade_resolve
  if [[ -z "$_rb_base" ]]; then
    echo "update-fleet: --remote-upgrade requires FORGE_FLEET_BASE_URL or FLEET_REMOTE_UPGRADE_URL or --remote-url" >&2
    return 1
  fi
  if [[ -z "$_rb_bearer" ]]; then
    echo "update-fleet: --remote-upgrade requires FORGE_FLEET_BEARER_TOKEN or --remote-bearer" >&2
    return 1
  fi
  _rb_url="${_rb_base}/v1/admin/upgrade"
  _rb_wait="${FLEET_REMOTE_UPGRADE_MAX_WAIT_SEC:-120}"
  _rb_allow_git="true"
  [[ "$REMOTE_STRICT_APT" -eq 1 ]] && _rb_allow_git="false"

  # Attempt ladder (each step is one POST; the first successful one wins):
  #   1. apt policy, cooperative wait        {require_apt_channel, allow_git_fallback}
  #   2. git-channel host (older Fleet answered migrate_to_apt_required) -> drop require_apt_channel
  #   3. dependents never reached stop_allowed (409 upgrade_blocked) -> on_timeout=force
  _rb_body_1="{\"mode\":\"upgrade\",\"require_apt_channel\":true,\"allow_git_fallback\":${_rb_allow_git},\"max_wait_sec\":${_rb_wait},\"on_timeout\":\"abort\"}"
  _rb_body_2="{\"mode\":\"upgrade\",\"max_wait_sec\":${_rb_wait},\"on_timeout\":\"abort\"}"
  _rb_body_3="{\"mode\":\"upgrade\",\"max_wait_sec\":30,\"on_timeout\":\"force\"}"
  if [[ "$REMOTE_STRICT_APT" -eq 1 ]]; then
    _rb_body_2="$_rb_body_1"
    _rb_body_3="{\"mode\":\"upgrade\",\"require_apt_channel\":true,\"max_wait_sec\":30,\"on_timeout\":\"force\"}"
  fi

  _rb_attempt=1
  _rb_body="$_rb_body_1"
  while :; do
    echo "[update-fleet] remote Fleet upgrade POST ${_rb_url} (attempt ${_rb_attempt}: ${_rb_body})"
    _rb_tmp="$(mktemp)"
    _rb_code="$(curl -sS --connect-timeout 10 --max-time "$(( _rb_wait + 90 ))" -o "$_rb_tmp" -w "%{http_code}" -X POST "$_rb_url" \
      -H "Authorization: Bearer ${_rb_bearer}" \
      -H "Content-Type: application/json" \
      -H "Accept: application/json" \
      -d "$_rb_body")" || _rb_code="000"
    if [[ "$_rb_code" != "200" && "$_rb_code" != "202" && "$_rb_code" != "400" && "$_rb_code" != "409" ]]; then
      echo "update-fleet: remote Fleet upgrade HTTP ${_rb_code}" >&2
      cat "$_rb_tmp" >&2 || true
      rm -f "$_rb_tmp"
      return 1
    fi
    export _UPDATE_FLEET_JSON_TMP="$_rb_tmp"
    _rb_verdict="$(python3 -c '
import json, os, pathlib, sys
path = pathlib.Path(os.environ["_UPDATE_FLEET_JSON_TMP"])
try:
    j = json.load(path.open(encoding="utf-8"))
except Exception as exc:  # noqa: BLE001
    print("[update-fleet] remote: non-JSON response:", exc, file=sys.stderr)
    print("fatal")
    sys.exit(0)
if j.get("ok") is True:
    note = (j.get("note") or "").strip() or "remote Fleet upgrade completed"
    print("[update-fleet] remote ok:", note, file=sys.stderr)
    if j.get("channel_fallback"):
        print("[update-fleet] WARN:", j.get("warning") or f"host upgraded via {j['channel_fallback']} git fallback", file=sys.stderr)
    print("ok")
    sys.exit(0)
err = str(j.get("error") or "unknown")
detail = (j.get("detail") or "").strip()
print("[update-fleet] remote error:", err, file=sys.stderr)
if detail:
    print(detail, file=sys.stderr)
if err == "upgrade_blocked":
    print("[update-fleet] waiting_on:", json.dumps(j.get("waiting_on") or []), file=sys.stderr)
cmd = j.get("system_root_install_command")
if cmd:
    print("[update-fleet] remote system install (run on Fleet host as root):", file=sys.stderr)
    print(cmd, file=sys.stderr)
print(err)
')"
    unset _UPDATE_FLEET_JSON_TMP || true
    rm -f "$_rb_tmp"
    case "$_rb_verdict" in
      ok) break ;;
      migrate_to_apt_required)
        if [[ "$REMOTE_STRICT_APT" -eq 1 || "$_rb_attempt" -ge 2 ]]; then
          echo "update-fleet: remote host is on a git channel and --remote-strict-apt is set (or fallback already tried); migrate it: land-fleet migrate-to-apt" >&2
          return 1
        fi
        echo "[update-fleet] WARN: remote Fleet is still on a git install channel — falling back to cooperative git upgrade via API (migrate to apt to retire this)." >&2
        _rb_body="$_rb_body_2"
        ;;
      upgrade_blocked)
        if [[ "$_rb_attempt" -ge 3 || "${FLEET_REMOTE_UPGRADE_FORCE_ON_BLOCK:-1}" != "1" ]]; then
          echo "update-fleet: dependents never allowed the Fleet stop; set FLEET_REMOTE_UPGRADE_FORCE_ON_BLOCK=1 or retry later." >&2
          return 1
        fi
        echo "[update-fleet] WARN: dependents did not reach stop_allowed within ${_rb_wait}s — retrying with on_timeout=force (Fleet-only restart; dependents keep running)." >&2
        _rb_body="$_rb_body_3"
        ;;
      *) return 1 ;;
    esac
    _rb_attempt=$(( _rb_attempt + 1 ))
  done

  remote_upgrade_verify
}

# Poll remote /v1/health until it reports the version we just pushed (bounded).
remote_upgrade_verify() {
  _rv_want="${NEW_VER:-}"
  [[ -n "$_rv_want" ]] || return 0
  _rv_deadline=$(( $(date +%s) + ${FLEET_REMOTE_UPGRADE_VERIFY_SEC:-180} ))
  _rv_seen=""
  while [[ "$(date +%s)" -lt "$_rv_deadline" ]]; do
    _rv_seen="$(curl -sS --connect-timeout 5 --max-time 15 "${_rb_base}/v1/health" 2>/dev/null \
      | python3 -c 'import json,sys
try:
    j=json.load(sys.stdin); v=j.get("version") or {}
    print(v.get("package_semver") if isinstance(v, dict) else v)
except Exception:
    print("")' 2>/dev/null || true)"
    if [[ "$_rv_seen" == "$_rv_want" ]]; then
      echo "[update-fleet] remote verified: /v1/health reports forge-fleet ${_rv_seen}"
      return 0
    fi
    sleep 5
  done
  echo "update-fleet: remote verify timed out — /v1/health reports '${_rv_seen:-unreachable}', expected ${_rv_want} (check GET /v1/admin/upgrade/status)" >&2
  return 1
}

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run] mode=$([[ "$STRICT" -eq 1 ]] && echo strict || echo dev), bump=$BUMP_KIND, push=$([[ "$NO_PUSH" -eq 1 ]] && echo no || echo yes), install=$([[ "$NO_INSTALL" -eq 1 ]] && echo no || echo yes), user=$([[ "$NO_USER" -eq 1 ]] && echo no || echo yes), remote_upgrade=$([[ "$REMOTE_UPGRADE" -eq 1 ]] && echo yes || echo no), publish_apt_cdn=$([[ "$PUBLISH_APT_CDN" -eq 1 ]] && echo yes || echo no)"
  if [[ "$REMOTE_UPGRADE" -eq 1 ]]; then
    remote_upgrade_resolve
    if [[ -z "$_rb_base" || -z "$_rb_bearer" ]]; then
      echo "[dry-run] would need FORGE_FLEET_BASE_URL (or FLEET_REMOTE_GIT_SELF_UPDATE_URL / --remote-url) and FORGE_FLEET_BEARER_TOKEN (or --remote-bearer)" >&2
    else
      echo "[dry-run] after successful push would: curl -sS -X POST ${_rb_base%/}/v1/admin/upgrade -H \"Authorization: Bearer ***\" -H Content-Type: application/json -d '{\"mode\":\"upgrade\"}'"
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

bash "${ROOT}/scripts/check-no-package-artifacts-in-git.sh"

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

if [[ "$PUBLISH_APT_CDN" -eq 1 ]] && [[ "$NO_PUSH" -eq 0 ]]; then
  echo "[update-fleet] publish-and-deploy-fleet-apt-cdn.sh…"
  bash "${ROOT}/scripts/publish-and-deploy-fleet-apt-cdn.sh"
elif [[ "$PUBLISH_APT_CDN" -eq 1 ]] && [[ "$NO_PUSH" -eq 1 ]]; then
  echo "[update-fleet] skipped publish-apt-cdn (--no-push)"
fi

if [[ "$REMOTE_UPGRADE" -eq 1 ]] && [[ "$NO_PUSH" -eq 0 ]]; then
  invoke_remote_upgrade || exit 1
elif [[ "$REMOTE_UPGRADE" -eq 1 ]] && [[ "$NO_PUSH" -eq 1 ]]; then
  echo "[update-fleet] skipped remote upgrade (--no-push)"
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
