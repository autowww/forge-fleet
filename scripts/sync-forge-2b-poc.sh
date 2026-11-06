#!/usr/bin/env bash
# Sync the forge-2b PoC code into forge-fleet/deploy/forge-2b-poc/vendor (git is the only code carrier).
#
# Sources (override with env):
#   FORGE_DCS_SRC   default ~/Code/forge-dcs/src/forge_dcs
#   FORGE_2B_SRC    default ~/Code/forge-models/forge-2b-poc/src/forge_2b
#   FORGE_2B_SKILLS default ~/Code/forge-models/forge-2b-poc/skills
#
# Records both source commits in vendor/SOURCES.txt so the deployed image is traceable.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$HERE/deploy/forge-2b-poc/vendor"
DCS_SRC="${FORGE_DCS_SRC:-$HOME/Code/forge-dcs/src/forge_dcs}"
SHIM_SRC="${FORGE_2B_SRC:-$HOME/Code/forge-models/forge-2b-poc/src/forge_2b}"
SKILLS_SRC="${FORGE_2B_SKILLS:-$HOME/Code/forge-models/forge-2b-poc/skills}"

[[ -d "$DCS_SRC" ]] || { echo "missing $DCS_SRC" >&2; exit 1; }
[[ -d "$SHIM_SRC" ]] || { echo "missing $SHIM_SRC" >&2; exit 1; }
[[ -d "$SKILLS_SRC" ]] || { echo "missing $SKILLS_SRC" >&2; exit 1; }

rm -rf "$DEST"
mkdir -p "$DEST"
rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' --exclude '.pytest_cache' "$DCS_SRC/" "$DEST/forge_dcs/"
rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' "$SHIM_SRC/" "$DEST/forge_2b/"
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
  echo "forge-dcs  $(git -C "$DCS_SRC" rev-parse HEAD 2>/dev/null || echo unknown) $(git -C "$DCS_SRC" status --porcelain 2>/dev/null | wc -l | xargs) dirty-paths"
  echo "forge-2b   $(git -C "$SHIM_SRC" rev-parse HEAD 2>/dev/null || echo unknown) $(git -C "$SHIM_SRC" status --porcelain 2>/dev/null | wc -l | xargs) dirty-paths"
  echo "synced_utc $(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$DEST/SOURCES.txt"

cat "$DEST/SOURCES.txt"
