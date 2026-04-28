#!/usr/bin/env bash
# update-fleet-unified-caddy.sh — on a host with forge-fleet cloned: pull latest Git,
# then run the Fleet + Ollama unified Caddy installer (non-interactive).
#
# Run from the forge-fleet repo root (directory containing pyproject.toml):
#   ./scripts/update-fleet-unified-caddy.sh
#
# Typical remote (user Fleet + ~/.config/forge-fleet/forge-fleet.env):
#   cd ~/forge-fleet && ./scripts/update-fleet-unified-caddy.sh
#
# System layout (needs root; tokens/ports in /etc/forge-fleet/caddy.env or env):
#   sudo -E LAYOUT=system ./scripts/update-fleet-unified-caddy.sh
#
# Override branch remote (default: current branch):
#   GIT_REMOTE_PULL=origin GIT_BRANCH=master ./scripts/update-fleet-unified-caddy.sh
#
# Requires: git, bash; same env vars as install-caddy-fleet-ollama-unified.sh --non-interactive
# (LAYOUT, FLEET_BEARER_TOKEN, ports, LLM_BEARER_TOKEN, optional CADDY_SITE_ADDRESS). Env files are sourced when present.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

[[ -f "$ROOT/pyproject.toml" ]] || {
  echo "update-fleet-unified-caddy: run from forge-fleet repo root (pyproject.toml missing): $ROOT" >&2
  exit 1
}

if [[ "${LAYOUT:-user}" == "system" ]] && [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  exec sudo -E "$ROOT/scripts/update-fleet-unified-caddy.sh" "$@"
fi

REMOTE="${GIT_REMOTE_PULL:-origin}"
BRANCH="${GIT_BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"

echo "[update-fleet-unified-caddy] git pull --rebase $REMOTE $BRANCH"
git pull --rebase "$REMOTE" "$BRANCH"

ENV_USER="${XDG_CONFIG_HOME:-$HOME/.config}/forge-fleet/forge-fleet.env"
ENV_SYSTEM="/etc/forge-fleet/caddy.env"

if [[ "${LAYOUT:-user}" == "system" ]]; then
  if [[ -f "$ENV_SYSTEM" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$ENV_SYSTEM"
    set +a
  fi
else
  if [[ -f "$ENV_USER" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_USER"
    set +a
  fi
fi

: "${LAYOUT:=user}"
export LAYOUT

exec "$ROOT/scripts/install-caddy-fleet-ollama-unified.sh" --non-interactive
