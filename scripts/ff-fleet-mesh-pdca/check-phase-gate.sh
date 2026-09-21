#!/usr/bin/env bash
# Forge Fleet Mesh PDCA phase gate.
# Usage: ./scripts/ff-fleet-mesh-pdca/check-phase-gate.sh <FM00|…|FM59|MW-0|…|MW-5|all>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PHASE="${1:-}"
PROMPT_DIR="${REPO_ROOT}/docs/prompts/ff-fleet-mesh-pdca"
MASTER_SEQ="${PROMPT_DIR}/00-master-sequence.md"
LEDGER="${PROMPT_DIR}/00_shared/00-requirements-ledger.md"
ASSUMPTIONS="${PROMPT_DIR}/00_shared/01-assumptions-and-non-goals.md"
OPEN_Q="${PROMPT_DIR}/00_shared/02-open-questions-ledger.md"
SEQUENCE_YAML="${SCRIPT_DIR}/SEQUENCE.yaml"
BOUNDARY_DOC="${REPO_ROOT}/docs/design/granite-operator-boundary.md"

CORE_REQ_IDS=(
  R00 R01 R02 R03 R04 R05
  R06 R07 R08 R09 R09a R09b
  R06c R06d R06e R06f R06g R06h
  R10 R11 R12 R13 R14 R15 R16 R17 R18 R19 R1a
  R20 R21 R22 R23 R24 R25 R26 R27
  R30 R31 R32 R33 R34
  R40 R41 R42 R43 R44
  R50 R51 R52 R53 R54
)

[[ -n "${PHASE}" ]] || {
  echo "usage: $0 <FM00|…|FM59|MW-0|…|MW-5|all>" >&2
  exit 1
}

cd "${REPO_ROOT}"

info() { echo "==> gate ${1}: $2"; }
fail() { echo "FAIL: $*" >&2; exit 1; }
require_file() { [[ -f "$1" ]] || fail "missing: $1"; }
require_prompt() {
  local phase="$1"
  local match
  match=$(find "${PROMPT_DIR}" -maxdepth 1 -name "${phase}-*.md" | head -1)
  [[ -n "${match}" ]] || fail "missing prompt for ${phase}"
}

require_req_ids_in_ledger() {
  local id
  for id in "$@"; do
    grep -q "| ${id} |" "${LEDGER}" || fail "requirements ledger missing ${id}"
  done
}

gate_stub_prompt() {
  local phase="$1"
  require_prompt "${phase}"
  info "${phase}" "stub gate (prompt file present)"
}

gate_fm00() {
  require_file "${MASTER_SEQ}"
  require_file "${SEQUENCE_YAML}"
  require_file "${SCRIPT_DIR}/check-phase-gate.sh"
  require_file "${PROMPT_DIR}/ORDER.txt"
  require_file "${PROMPT_DIR}/_prompt-template.md"
  require_file "${LEDGER}"
  require_file "${ASSUMPTIONS}"
  require_file "${OPEN_Q}"
  require_prompt FM00
  grep -q 'Composer 2.5' "${MASTER_SEQ}" || fail "master sequence must specify Composer 2.5"
  grep -q 'FM59' "${SEQUENCE_YAML}" || fail "SEQUENCE missing FM59"
  grep -q 'MW-0b' "${MASTER_SEQ}" || fail "master sequence missing MW-0b apt section"
  grep -q 'packages.forgesdlc.com' "${ASSUMPTIONS}" || fail "assumptions must document apt CDN URL"
  grep -q 'install.sh' "${ASSUMPTIONS}" || fail "assumptions must document install.sh bootstrap"
  require_req_ids_in_ledger "${CORE_REQ_IDS[@]}"
  grep -q 'NFR08' "${LEDGER}" || fail "ledger missing NFR08"
  info FM00 "scaffold OK"
}

gate_fm05() {
  gate_fm00
  require_prompt FM05
  info FM05 "stub (packaging not implemented yet)"
}

gate_fm09() {
  gate_fm05
  require_prompt FM09
  info FM09 "stub (install.sh not implemented yet)"
}

run_gate() {
  case "$1" in
    FM00) gate_fm00 ;;
    FM01|FM02) gate_fm00; gate_stub_prompt "$1" ;;
    FM05) gate_fm05 ;;
    FM06|FM07|FM08) gate_fm00; gate_stub_prompt "$1" ;;
    FM09) gate_fm09 ;;
    FM10|FM19|FM59) gate_fm00; gate_stub_prompt "$1" ;;
    MW-0) gate_fm00 ;;
    MW-0b) gate_fm05 ;;
    MW-1) gate_fm00; gate_stub_prompt FM10 ;;
    all)
      gate_fm00
      for p in FM05 FM06 FM07 FM08 FM09; do
        gate_stub_prompt "$p"
      done
      ;;
    *)
      fail "unknown phase: $1"
      ;;
  esac
}

run_gate "${PHASE}"
echo "PASS: ${PHASE}"
