#!/usr/bin/env bash
# Copy Open WebUI docker volumes from Granite to Mercury (run from operator laptop).
set -euo pipefail
SRC="${FORGE_OPENWEBUI_SRC_SSH:-granite}"
DST="${FORGE_OPENWEBUI_DST_SSH:-mercury}"
for vol in forge_open_webui_data forge_open_webui_pgdata; do
  echo "== $vol =="
  ssh -o BatchMode=yes "$SRC" "docker run --rm -v ${vol}:/from alpine tar -C /from -cf - ." \
    | ssh -o BatchMode=yes "$DST" "docker volume create ${vol} >/dev/null 2>&1 || true; docker run --rm -i -v ${vol}:/to alpine tar -C /to -xf -"
done
echo "Volume migration done."