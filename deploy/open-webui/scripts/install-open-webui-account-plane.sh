#!/usr/bin/env bash
# Install systemd user units for Open WebUI web-account Chromium CDP + bridge (one profile per account).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACCOUNTS_FILE="${1:-$ROOT/accounts.json}"
[[ -f "$ACCOUNTS_FILE" ]] || ACCOUNTS_FILE="$ROOT/accounts.example.json"
[[ -f "$ACCOUNTS_FILE" ]] || { echo "missing accounts.json" >&2; exit 1; }

UNIT_DIR="${HOME}/.config/systemd/user"
mkdir -p "$UNIT_DIR"
ENSURE="${ROOT}/scripts/ensure-account-edge-cdp.sh"
BRIDGE_MODULE="forge_web_bridge"

parse_accounts() {
  python3 - "$ACCOUNTS_FILE" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for row in data.get("accounts") or []:
    if not isinstance(row, dict):
        continue
    slug = str(row.get("slug") or "").strip()
    if not slug:
        continue
    print(
        "\t".join(
            [
                slug,
                str(row.get("provider") or "chatgpt"),
                str(row.get("cdp_port") or ""),
                str(row.get("bridge_port") or ""),
                str(row.get("profile_dir") or f"chromium-granite-{slug}"),
                str(row.get("open_webui_model_id") or slug),
            ]
        )
    )
PY
}

while IFS=$'\t' read -r slug provider cdp_port bridge_port profile_dir model_id; do
  [[ -n "$slug" ]] || continue
  edge_unit="forge-open-webui-edge-${slug}.service"
  bridge_unit="forge-open-webui-bridge-${slug}.service"

  cat >"${UNIT_DIR}/${edge_unit}" <<EOF
[Unit]
Description=Open WebUI account Chromium CDP (${slug})
After=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
Environment=FORGE_OPEN_WEBUI_HEADLESS=${FORGE_OPEN_WEBUI_HEADLESS:-1}
Environment=FORGE_OPEN_WEBUI_BROWSER=${FORGE_OPEN_WEBUI_BROWSER:-google-chrome}
Environment=FORGE_LCDL_SRC=${HOME}/forge-lcdl
Environment=FORGE_OPEN_WEBUI_ACCOUNT_SLUG=${slug}
Environment=FORGE_OPEN_WEBUI_CDP_PORT=${cdp_port}
Environment=FORGE_OPEN_WEBUI_PROFILE_DIR=${profile_dir}
ExecStart=${ENSURE}

[Install]
WantedBy=default.target
EOF

  cat >"${UNIT_DIR}/${bridge_unit}" <<EOF
[Unit]
Description=Open WebUI web bridge (${slug} / ${provider})
After=network-online.target forge-open-webui-edge-${slug}.service
Requires=forge-open-webui-edge-${slug}.service

[Service]
Type=simple
Restart=on-failure
RestartSec=5
Environment=FORGE_WEB_BRIDGE_PROVIDER=${provider}
Environment=FORGE_WEB_BRIDGE_CDP_URL=http://127.0.0.1:${cdp_port}
# 0.0.0.0 so forge-open-webui (Docker) can reach bridges via host.docker.internal
Environment=FORGE_WEB_BRIDGE_LISTEN_HOST=${FORGE_WEB_BRIDGE_LISTEN_HOST:-0.0.0.0}
Environment=FORGE_WEB_BRIDGE_LISTEN_PORT=${bridge_port}
Environment=FORGE_WEB_BRIDGE_MODEL_ID=${model_id}
Environment=PYTHONPATH=${HOME}/forge-lcdl/src
WorkingDirectory=${ROOT}/bridge
ExecStart=${HOME}/.local/share/forge-fleet/.venv/bin/python3 -m ${BRIDGE_MODULE}
# Fallback when fleet venv missing:
# ExecStart=python3 -m ${BRIDGE_MODULE}

[Install]
WantedBy=default.target
EOF

  systemctl --user enable "forge-open-webui-edge-${slug}.service" "forge-open-webui-bridge-${slug}.service"
  echo "installed: ${slug} cdp=${cdp_port} bridge=${bridge_port}"
done < <(parse_accounts)

systemctl --user daemon-reload
echo "Headless Granite: FORGE_OPEN_WEBUI_HEADLESS=1 (default). Sign in via Fleet CDP stream (no host GUI)."
echo "Optional: pack signed-in profile on laptop — scripts/pack-open-webui-edge-profile.sh"
