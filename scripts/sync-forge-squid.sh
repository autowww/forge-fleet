#!/usr/bin/env bash
# Sync forge-squid shim sources into forge-fleet/deploy/forge-squid/vendor (git is the only code carrier).
#
# Sources (override with env):
#   FORGE_DCS_SRC      default ~/Code/forge-dcs/src/forge_dcs
#   FORGE_SQUID_SRC    default ~/Code/forge-models/forge-squid/src/forge_squid
#   FORGE_SQUID_SKILLS default ~/Code/forge-models/forge-squid/skills
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$HERE/deploy/forge-squid/vendor"
DCS_SRC="${FORGE_DCS_SRC:-$HOME/Code/forge-dcs/src/forge_dcs}"
SHIM_SRC="${FORGE_SQUID_SRC:-$HOME/Code/forge-models/forge-squid/src/forge_squid}"
if [[ ! -d "$SHIM_SRC" ]]; then
  SHIM_SRC="${FORGE_SQUID_SRC:-$HOME/Code/forge-models/forge-2b-poc/src/forge_squid}"
fi
SKILLS_SRC="${FORGE_SQUID_SKILLS:-$HOME/Code/forge-models/forge-squid/skills}"
if [[ ! -d "$SKILLS_SRC" ]]; then
  SKILLS_SRC="${FORGE_SQUID_SKILLS:-$HOME/Code/forge-models/forge-2b-poc/skills}"
fi

[[ -d "$DCS_SRC" ]] || { echo "missing $DCS_SRC" >&2; exit 1; }
[[ -d "$SHIM_SRC" ]] || { echo "missing $SHIM_SRC" >&2; exit 1; }
[[ -d "$SKILLS_SRC" ]] || { echo "missing $SKILLS_SRC" >&2; exit 1; }

rm -rf "$DEST"
mkdir -p "$DEST"
rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' --exclude '.pytest_cache' "$DCS_SRC/" "$DEST/forge_dcs/"
rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' "$SHIM_SRC/" "$DEST/forge_squid/"
rsync -a --delete --exclude '__pycache__' "$SKILLS_SRC/" "$DEST/skills/"

cat > "$DEST/requirements.txt" <<'EOF'
fastapi>=0.115,<1
pydantic>=2.7,<3
jsonschema>=4.21,<5
referencing>=0.35
httpx>=0.27,<1
uvicorn>=0.30,<1
pyyaml>=6,<7
EOF

{
  echo "forge-dcs    $(git -C "$DCS_SRC" rev-parse HEAD 2>/dev/null || echo unknown) $(git -C "$DCS_SRC" status --porcelain 2>/dev/null | wc -l | xargs) dirty-paths"
  echo "forge-squid  $(git -C "$SHIM_SRC" rev-parse HEAD 2>/dev/null || echo unknown) $(git -C "$SHIM_SRC" status --porcelain 2>/dev/null | wc -l | xargs) dirty-paths"
  echo "synced_utc   $(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$DEST/SOURCES.txt"

cat "$DEST/SOURCES.txt"
