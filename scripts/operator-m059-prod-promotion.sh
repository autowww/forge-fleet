#!/usr/bin/env bash
# Operator: prod m051/m059 promotion only after dev gate green (5c).
set -euo pipefail

echo "Prerequisites:"
echo "  1. dev-gate-validate.sh green"
echo "  2. studio-ui dev-gate-page-walk.spec.ts green (before and after m059 rehearsal on dev)"
echo "  3. dictionary_parity_report.py --fail-on-gaps green on prod"
echo "  4. explicit operator approval for contract drops"
echo ""
echo "Example prod rollout with verified backup (m059):"
echo '  curl -X POST "$FORGE_FLEET_BASE_URL/v1/managed-services/market-studio/rollout" \'
echo '    -H "Authorization: Bearer $FORGE_FLEET_BEARER_TOKEN" \'
echo '    -H "Content-Type: application/json" \'
echo '    -d '"'"'{"confirm_dictionary_drops": true, "run_schema_migrate": true}'"'"
exit 0
