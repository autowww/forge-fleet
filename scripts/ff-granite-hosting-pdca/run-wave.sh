#!/usr/bin/env bash
# Print wave prompt bundle for Cursor orchestration.
# Usage: ./scripts/ff-granite-hosting-pdca/run-wave.sh GW-0|GW-1|…|GW-6

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
WAVE="${1:-}"
[[ -n "${WAVE}" ]] || { echo "usage: $0 <GW-0|GW-1|GW-2|GW-3|GW-4|GW-5|GW-6>" >&2; exit 1; }

MASTER="${REPO_ROOT}/docs/prompts/ff-granite-hosting-pdca/00-master-sequence.md"
echo "# Wave ${WAVE}"
echo ""
echo "Read master sequence: ${MASTER}"
echo ""
echo "Read requirements ledger: ${REPO_ROOT}/docs/prompts/ff-granite-hosting-pdca/00_shared/00-requirements-ledger.md"
echo ""
echo "Granite operator boundary: ${REPO_ROOT}/docs/design/granite-operator-boundary.md"
echo ""
echo "Run phases in order; gate each with:"
echo "  scripts/ff-granite-hosting-pdca/check-phase-gate.sh <phase>"
echo ""
echo "Wave closeout:"
echo "  scripts/ff-granite-hosting-pdca/check-phase-gate.sh ${WAVE}"
echo ""

case "${WAVE}" in
  GW-0) phases=(FH00 FH01 FH02 FH03 FH04 FH05) ;;
  GW-1) phases=(FH10 FH11 FH12 FH13 FH14 FH15 FH16 FH17 FH18) ;;
  GW-2) phases=(FH20 FH21 FH22 FH23 FH24 FH25 FH26 FH27 FH28) ;;
  GW-3) phases=(FH30 FH31 FH32 FH33 FH34 FH35 FH36 FH37 FH38) ;;
  GW-4) phases=(FH40 FH41 FH42 FH43 FH44 FH45 FH46 FH47 FH48) ;;
  GW-5) phases=(FH50 FH51 FH52 FH53 FH54 FH55 FH56 FH57 FH58 FH59) ;;
  GW-6) phases=(FH60 FH61 FH62 FH63 FH64 FH65 FH70) ;;
  *) echo "unknown wave: ${WAVE}" >&2; exit 1 ;;
esac

for p in "${phases[@]}"; do
  match=$(find "${REPO_ROOT}/docs/prompts/ff-granite-hosting-pdca" -maxdepth 1 -name "${p}-*.md" | head -1)
  if [[ -n "${match}" ]]; then
    echo "- ${p}: ${match}"
  else
    echo "- ${p}: (prompt pending — add ${p}-*.md before execution)"
  fi
done
