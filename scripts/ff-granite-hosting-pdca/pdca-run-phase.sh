#!/usr/bin/env bash
# Forge Fleet Granite hosting PDCA phase runner.
# Usage: ./scripts/ff-granite-hosting-pdca/pdca-run-phase.sh <FH00|…|FH70|GW-0|all> [check|print|agent]

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PHASE="${1:-}"
MODE="${2:-check}"

[[ -n "${PHASE}" ]] || {
  echo "usage: $0 <FH00|…|FH70|GW-0|…|GW-6|all> [check|print|agent]" >&2
  exit 1
}

PROMPT_DIR="${REPO_ROOT}/docs/prompts/ff-granite-hosting-pdca"

resolve_prompt() {
  local phase="$1"
  find "${PROMPT_DIR}" -maxdepth 1 -name "${phase}-*.md" | head -1
}

if [[ "${MODE}" == "check" ]]; then
  exec "${SCRIPT_DIR}/check-phase-gate.sh" "${PHASE}"
fi

if [[ "${MODE}" == "print" ]]; then
  match="$(resolve_prompt "${PHASE}")"
  [[ -n "${match}" ]] || { echo "no prompt for ${PHASE}" >&2; exit 1; }
  echo "Executor: Composer 2.5"
  echo "Prompt: ${match}"
  echo ""
  cat "${match}"
  exit 0
fi

if [[ "${MODE}" == "agent" ]]; then
  match="$(resolve_prompt "${PHASE}")"
  [[ -n "${match}" ]] || { echo "no prompt for ${PHASE}" >&2; exit 1; }
  if command -v agent >/dev/null 2>&1; then
    exec agent -p --model composer-2.5 "$(cat "${match}")"
  fi
  echo "agent CLI not found; paste prompt from:" >&2
  echo "  ${match}" >&2
  exit 0
fi

echo "unknown mode: ${MODE} (use check|print|agent)" >&2
exit 1
