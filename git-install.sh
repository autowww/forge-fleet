#!/usr/bin/env bash
# git-install.sh — first-time setup on a machine where you only have a **git clone** of forge-fleet.
#
# Does: ``git submodule update --init --recursive`` (kitchensink + blueprints are required by install-update),
# then runs either the **system** install (default) or **user** install.
#
# Typical (production-style, /opt + systemd system unit, port 18765):
#   git clone <url> forge-fleet && cd forge-fleet && ./git-install.sh
#
# User-level (no sudo, systemd --user, port 18766 by default):
#   ./git-install.sh --user
#
# Only submodules + sanity checks (no sudo):
#   ./git-install.sh --prepare-only
#
# Extra flags are forwarded to ``install-update.sh`` or ``install-user.sh`` after ``--``:
#   ./git-install.sh -- --dry-run
#   ./git-install.sh -- --no-restart
#
# Full narrative: see ``docs/GIT-INSTALL.md`` and the **Install from git** section in ``README.md``.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

MODE=system
DRY_RUN=0
PASSTHRU=()

usage() {
  sed -n '2,/^# Full narrative:/p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user) MODE=user; shift ;;
    --system) MODE=system; shift ;;
    --prepare-only) MODE=prepare; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage 0 ;;
    --) shift; PASSTHRU+=("$@"); break ;;
    -*)
      echo "unknown option: $1 (use -- to pass flags to install-update.sh)" >&2
      usage 2
      ;;
    *)
      echo "unexpected argument: $1" >&2
      usage 2
      ;;
  esac
done

die() { echo "git-install.sh: $*" >&2; exit 1; }

[[ -d "$ROOT/fleet_server" ]] || die "missing fleet_server/ — run this script from the forge-fleet repo root"
[[ -f "$ROOT/pyproject.toml" ]] || die "missing pyproject.toml"

command -v git >/dev/null 2>&1 || die "git not found"
if [[ ! -d "$ROOT/.git" ]]; then
  echo "git-install.sh: warning: no .git directory — did you copy a tarball? Submodules may still run." >&2
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run] would: git submodule update --init --recursive; mode=$MODE"
  exit 0
fi

echo "[git-install] submodule update --init --recursive …"
git -C "$ROOT" submodule update --init --recursive

if [[ ! -e "$ROOT/kitchensink/.git" && ! -f "$ROOT/kitchensink/README.md" ]]; then
  die "kitchensink/ looks empty after submodule update — check network/submodule URLs (see docs/GIT-INSTALL.md)"
fi

if [[ "$MODE" == prepare ]]; then
  echo "[git-install] --prepare-only: submodules ready. Next: ./git-install.sh   or   sudo ./install-update.sh"
  exit 0
fi

if [[ "$MODE" == user ]]; then
  chmod +x "$ROOT/install-user.sh" 2>/dev/null || true
  echo "[git-install] running install-user.sh …"
  exec "$ROOT/install-user.sh" "${PASSTHRU[@]}"
fi

chmod +x "$ROOT/install-update.sh" 2>/dev/null || true
echo "[git-install] running install-update.sh (requires sudo) …"
sudo env FLEET_SRC="$ROOT" "$ROOT/install-update.sh" "${PASSTHRU[@]}"
echo "[git-install] done. Configure /etc/forge-fleet/forge-fleet.env (e.g. FLEET_BEARER_TOKEN); see docs/GIT-INSTALL.md"
