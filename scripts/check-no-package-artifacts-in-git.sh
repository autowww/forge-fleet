#!/usr/bin/env bash
# Fail if Fleet package build outputs are tracked or staged in git (CDN-only policy).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

patterns=(
  '*.deb'
  'dist/debs'
  'dist/apt-publish'
  'dist/staging'
)

fail=0
for pat in "${patterns[@]}"; do
  if git ls-files --error-unmatch "$pat" 2>/dev/null | grep -q .; then
    echo "check-no-package-artifacts-in-git: tracked files match $pat" >&2
    git ls-files "$pat" >&2 || true
    fail=1
  fi
done

if git diff --cached --name-only | grep -E '\.deb$|^dist/(debs|apt-publish|staging)/' >/dev/null 2>&1; then
  echo "check-no-package-artifacts-in-git: staged package artifacts (uncommit; use publish-fleet-apt.sh + packages CDN)" >&2
  git diff --cached --name-only | grep -E '\.deb$|^dist/' >&2 || true
  fail=1
fi

if [[ "$fail" -ne 0 ]]; then
  echo "check-no-package-artifacts-in-git: see docs/maintainers/05-fleet-apt-cdn-publish.md" >&2
  exit 1
fi

echo "check-no-package-artifacts-in-git: ok"
