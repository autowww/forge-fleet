#!/usr/bin/env bash
# R06 — grep operator runbooks for forbidden Granite SSH deploy/data patterns.
# Usage: ./scripts/ff-granite-hosting-pdca/check-granite-boundary.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BOUNDARY_DOC="${REPO_ROOT}/docs/design/granite-operator-boundary.md"

cd "${REPO_ROOT}"

fail() { echo "FAIL: $*" >&2; exit 1; }
info() { echo "==> granite-boundary: $*"; }

[[ -f "${BOUNDARY_DOC}" ]] || fail "missing boundary doc: ${BOUNDARY_DOC}"

# Runbooks and operator docs to scan (extend as migration runbooks land).
RUNBOOK_GLOBS=(
  "docs/build-201/*.md"
  "docs/learn-101/*.md"
  "docs/start/*.md"
  "docs/examples/*.md"
  "docs/prompts/ff-granite-hosting-pdca/*.md"
)

shopt -s nullglob
RUNBOOKS=()
for g in "${RUNBOOK_GLOBS[@]}"; do
  for f in ${g}; do
    RUNBOOKS+=("${f}")
  done
done
shopt -u nullglob

[[ ${#RUNBOOKS[@]} -gt 0 ]] || fail "no runbook files matched for boundary scan"

# Patterns forbidden for Market Studio migration/deploy over Granite SSH.
# Allow documented negation lines (leading "Forbidden" table context) — we flag
# instructional examples only when they appear as imperative deploy steps outside
# the boundary doc's forbidden table.
FORBIDDEN_PATTERNS=(
  'scp[[:space:]].*(market|migration|bundle|corpus|forge-market)'
  'rsync[[:space:]].*(market|migration|bundle|corpus|forge-market)'
  'docker[[:space:]]+compose[[:space:]].*(market|forge-market-studio)'
  'docker-compose[[:space:]].*(market|forge-market-studio)'
)

VIOLATIONS=0

for rb in "${RUNBOOKS[@]}"; do
  [[ -f "${rb}" ]] || continue
  # Skip the boundary doc itself (it documents forbidden patterns by design).
  [[ "${rb}" == "${BOUNDARY_DOC}" ]] && continue

  for pat in "${FORBIDDEN_PATTERNS[@]}"; do
    if grep -Einq "${pat}" "${rb}"; then
      echo "FORBIDDEN pattern in ${rb}:" >&2
      grep -Ein "${pat}" "${rb}" >&2 || true
      VIOLATIONS=$((VIOLATIONS + 1))
    fi
  done
done

if [[ ${VIOLATIONS} -gt 0 ]]; then
  fail "${VIOLATIONS} runbook line(s) match forbidden Granite SSH deploy/data patterns (R06)"
fi

info "CHECK GREEN — ${#RUNBOOKS[@]} runbook file(s) scanned"
