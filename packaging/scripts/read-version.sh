#!/usr/bin/env bash
# Print package version from pyproject.toml (e.g. 0.3.106).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 - "$ROOT/pyproject.toml" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
if not m:
    raise SystemExit("version not found in pyproject.toml")
print(m.group(1))
PY
