#!/usr/bin/env bash
# Launch or attach dedicated Chromium CDP for one Open WebUI web account (Granite host).
set -euo pipefail

SLUG="${FORGE_OPEN_WEBUI_ACCOUNT_SLUG:?set FORGE_OPEN_WEBUI_ACCOUNT_SLUG}"
CDP_PORT="${FORGE_OPEN_WEBUI_CDP_PORT:?set FORGE_OPEN_WEBUI_CDP_PORT}"
PROFILE_NAME="${FORGE_OPEN_WEBUI_PROFILE_DIR:-chromium-granite-${SLUG}}"
PROFILE="${HOME}/.config/${PROFILE_NAME}"

FLEET_SRC="${FORGE_FLEET_SRC:-$HOME/.local/share/forge-fleet}"
LCDL_SRC="${FORGE_LCDL_SRC:-$HOME/Code/forge-lcdl}"
if [[ ! -d "$LCDL_SRC/src/forge_lcdl" ]]; then
  LCDL_SRC="$(cd "$(dirname "$0")/../../../.." && pwd)/forge-lcdl"
fi

export PYTHONPATH="${LCDL_SRC}/src${PYTHONPATH:+:$PYTHONPATH}"
PYTHON="${FLEET_SRC}/.venv/bin/python3"
[[ -x "$PYTHON" ]] || PYTHON="python3"

exec "$PYTHON" - "$PROFILE" "$CDP_PORT" <<'PY'
import os
import shutil
import subprocess
import sys
from pathlib import Path

from forge_lcdl.playwright.edge_cdp_attach import (
    cdp_endpoint_alive,
    cdp_http_url,
    operator_edge_cdp_launch_argv,
)

profile = Path(sys.argv[1]).expanduser().resolve()
port = int(sys.argv[2])
cdp_url = cdp_http_url(port)

if cdp_endpoint_alive(cdp_url):
    print(f"ok=1 cdp_url={cdp_url} profile={profile}", flush=True)
    raise SystemExit(0)

profile.mkdir(parents=True, exist_ok=True)

browser = (os.environ.get("FORGE_OPEN_WEBUI_BROWSER") or "").strip()
if not browser:
    for name in (
        "google-chrome-stable",
        "google-chrome",
        "chromium-browser",
        "chromium",
    ):
        found = shutil.which(name)
        if found:
            browser = found
            break
if not browser:
    print("error=chromium_binary_not_found", flush=True)
    raise SystemExit(1)

headless = os.environ.get("FORGE_OPEN_WEBUI_HEADLESS", "").strip() in ("1", "true", "yes")
argv = operator_edge_cdp_launch_argv(
    browser, profile, port, start_minimized=not headless
)
if headless:
    # No X11/Wayland on headless Granite — CDP + Fleet stream for sign-in.
    argv[1:1] = ["--headless=new", "--disable-gpu"]
    argv = [a for a in argv if a != "--start-minimized"]

subprocess.Popen(
    argv,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    start_new_session=True,
)
print(
    f"launched=1 headless={int(headless)} cdp_url={cdp_url} profile={profile}",
    flush=True,
)
PY
