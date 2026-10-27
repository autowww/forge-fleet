#!/usr/bin/env bash
# Extract Fleet migration bundle (packed Edge profile) into ~/.config/<profile_dir>.
set -euo pipefail

MID="${1:?usage: $0 <migration_id>}"
FLEET_DATA="${FORGE_FLEET_DATA:-$HOME/.local/share/forge-fleet}"
EXT="$FLEET_DATA/migration-bundles/$MID/extracted"
META="$EXT/bundle/.open-webui-profile.json"
[[ -f "$META" ]] || { echo "missing $META — wrong bundle?" >&2; exit 1; }

python3 - "$META" "$EXT/bundle" <<'PY'
import json
import shutil
import sys
from pathlib import Path

meta = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
bundle = Path(sys.argv[2])
profile_dir = str(meta["profile_dir"])
slug = meta.get("slug", "")
src = bundle / profile_dir
dest = Path.home() / ".config" / profile_dir
if not src.is_dir():
    raise SystemExit(f"missing profile tree {src}")
if dest.exists():
    shutil.rmtree(dest)
shutil.copytree(src, dest)
print(f"installed profile slug={slug} dest={dest}")
PY

echo "Restart edge unit: systemctl --user restart forge-open-webui-edge-<slug>.service"
