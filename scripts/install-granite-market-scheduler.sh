#!/usr/bin/env bash
# Install systemd user timer on Granite host for Market Studio gateway scheduler.
set -euo pipefail

FLEET_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MARKET_ROOT="${FORGE_MARKET_ROOT:-}"
if [[ -z "$MARKET_ROOT" ]]; then
  for candidate in \
    "$FLEET_ROOT/../forge-market" \
    "$HOME/forge-market" \
    "$HOME/Code/forge-market"; do
    if [[ -f "$candidate/scripts/granite-market-scheduler-run.sh" ]]; then
      MARKET_ROOT="$candidate"
      break
    fi
  done
fi
[[ -n "$MARKET_ROOT" ]] || { echo "ERROR: forge-market checkout not found" >&2; exit 1; }

UNIT_DIR="${HOME}/.config/systemd/user"
SERVICE_NAME="forge-market-granite-scheduler.service"
TIMER_NAME="forge-market-granite-scheduler.timer"
ENV_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/forge-fleet/forge-market-granite.env"

mkdir -p "$(dirname "$ENV_FILE")" "$UNIT_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  cat >"$ENV_FILE" <<EOF
# Granite Market Studio scheduler — gateway bearer + optional Flex/IBKR tokens
FORGE_MARKET_REMOTE_API=https://granite.forgedc.net/v1/app-gateways/market-studio
FORGE_FLEET_BEARER_TOKEN=
FORGE_MARKET_SCHED_WATCHLIST=semiconductors
FORGE_MARKET_SCHED_MOCK=0
FORGE_MARKET_SCHED_IBKR=0
# SEC fair-access contact — also consumed by market-studio rollout compose
FORGE_MARKET_SEC_CONTACT=
EOF
  echo "Created $ENV_FILE — set FORGE_FLEET_BEARER_TOKEN before enabling timer"
fi

cat >"${UNIT_DIR}/${SERVICE_NAME}" <<EOF
[Unit]
Description=Forge Market Granite gateway scheduler (SEC + pipeline)
After=network-online.target

[Service]
Type=oneshot
EnvironmentFile=${ENV_FILE}
WorkingDirectory=${MARKET_ROOT}
ExecStart=${MARKET_ROOT}/scripts/granite-market-scheduler-run.sh
EOF

cat >"${UNIT_DIR}/${TIMER_NAME}" <<EOF
[Unit]
Description=Daily Forge Market Granite scheduler

[Timer]
OnCalendar=Mon-Fri 06:30
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now "${TIMER_NAME}"
echo "Installed ${TIMER_NAME} — check: systemctl --user status ${TIMER_NAME}"
