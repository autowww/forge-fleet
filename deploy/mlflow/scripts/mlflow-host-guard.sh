#!/usr/bin/env bash
# MLflow Venus-only install guard.
set -euo pipefail

mlflow_host_allowed() {
  if [[ "${FORGE_MLFLOW_FORCE_LOCAL:-}" == "1" ]]; then
    return 0
  fi
  local role="${FORGE_HOST_ROLE:-${FORGE_MLFLOW_HOST:-}}"
  role="${role,,}"
  if [[ "$role" == "venus" ]]; then
    return 0
  fi
  local hn
  hn="$(hostname -s 2>/dev/null | tr '[:upper:]' '[:lower:]')"
  case "$hn" in
    venus | fw3gsg3 | fw3g*)
      return 0
      ;;
  esac
  if [[ -r /etc/forge/host-role ]] && grep -qiE '^venus' /etc/forge/host-role 2>/dev/null; then
    return 0
  fi
  return 1
}

mlflow_require_venus_host() {
  if mlflow_host_allowed; then
    return 0
  fi
  echo "MLflow deploy is Venus-only; refusing on host $(hostname -s)." >&2
  echo "Public UI: https://mlflow.forgedc.net" >&2
  return 1
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  mlflow_require_venus_host
fi