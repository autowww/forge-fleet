#!/usr/bin/env bash
# Open WebUI stack (compose, DB sync, account plane) runs on Granite production hosts only — not the operator ASUS laptop.
set -euo pipefail

open_webui_host_allowed() {
  if [[ "${FORGE_OPEN_WEBUI_FORCE_LOCAL:-}" == "1" ]]; then
    return 0
  fi
  local role="${FORGE_HOST_ROLE:-${FORGE_OPEN_WEBUI_HOST:-}}"
  role="${role,,}"
  if [[ "$role" == "granite" ]]; then
    return 0
  fi
  local hn
  hn="$(hostname -s 2>/dev/null | tr '[:upper:]' '[:lower:]')"
  case "$hn" in
    granite | mercury | fos1 | fos-1 | precision | s7550 | 7550)
      return 0
      ;;
  esac
  if [[ -r /etc/forge/host-role ]] && grep -qiE '^(granite|mercury|fos1)' /etc/forge/host-role 2>/dev/null; then
    return 0
  fi
  return 1
}

open_webui_require_granite_host() {
  if open_webui_host_allowed; then
    return 0
  fi
  echo "Open WebUI is Granite-only; refusing on host $(hostname -s)." >&2
  echo "Use https://webui.forgedc.net (Granite). Fleet: scripts/rollout-open-webui.sh on Granite." >&2
  echo "To stop local containers: deploy/open-webui/scripts/stop-open-webui-local.sh" >&2
  return 1
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  open_webui_require_granite_host
fi
