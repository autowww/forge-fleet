#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "=== 1. pytest ==="
python3 -m pytest tests/test_admin_shell.py -q
echo "exit_code: $?"

echo ""
echo "=== 2. bundle_admin_html ==="
python3 scripts/bundle_admin_html.py
echo "exit_code: $?"

echo ""
echo "=== 3. wc -l ==="
wc -l fleet_server/static/admin.html fleet_server/static/admin/html_src/**/*.html
echo "exit_code: $?"

echo ""
echo "=== 4. assemble vs bundled ==="
python3 -c "
from pathlib import Path
import sys
sys.path.insert(0, '.')
from fleet_server.admin_shell import assemble_admin_html
html = assemble_admin_html(html_src=Path('fleet_server/static/admin/html_src'))
bundled = Path('fleet_server/static/admin.html').read_text()
print('assembled lines', len(html.splitlines()))
print('bundled lines', len(bundled.splitlines()))
print('match', html == bundled)
"
echo "exit_code: $?"
