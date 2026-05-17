#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 scripts/check-docs-json.py
python3 scripts/check-docs-links.py
python3 scripts/check-docs-contracts.py
python3 scripts/check-docs-examples.py
python3 scripts/check-docs-public-copy.py
python3 scripts/check-openapi-quality.py
python3 scripts/check-docs-assets.py
if python3 -c "import jsonschema" 2>/dev/null; then
  python3 scripts/check-schema-examples.py
else
  echo "check-docs-all: SKIP check-schema-examples (pip install -e '.[docs]')"
fi
python3 scripts/check-version-consistency.py
echo "check-docs-all: OK"
