#!/usr/bin/env bash
# Dummy rollout for generic API contract tests.
set -euo pipefail

FLEET_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/fleet-rollout-step.sh
source "${FLEET_ROOT}/scripts/fleet-rollout-step.sh"

_SERVICE_ID="${FLEET_DUMMY_SERVICE_ID:-dummy-service}"
_LOG_PATH="${FLEET_DUMMY_ROLLOUT_LOG:-$HOME/.local/state/forge-fleet/rollout-logs/${_SERVICE_ID}.log}"

fleet_rollout_begin "${_SERVICE_ID}" "${_LOG_PATH}"
fleet_rollout_step "prepare" "Dummy prepare"
sleep 0.2
fleet_rollout_step "sync" "Dummy sync"
sleep 0.2
if [[ "${FLEET_DUMMY_ROLLOUT_FAIL:-0}" == "1" ]]; then
  fleet_rollout_failed "sync" "dummy failure requested"
  exit 1
fi
fleet_rollout_step "finalize" "Dummy finalize"
fleet_rollout_done
