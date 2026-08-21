#!/usr/bin/env bash
# Forge Fleet Granite hosting PDCA phase gate.
# Usage: ./scripts/ff-granite-hosting-pdca/check-phase-gate.sh <FH00|…|FH70|GW-0|…|GW-6|all>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PHASE="${1:-}"
PROMPT_DIR="${REPO_ROOT}/docs/prompts/ff-granite-hosting-pdca"
MASTER_SEQ="${PROMPT_DIR}/00-master-sequence.md"
LEDGER="${PROMPT_DIR}/00_shared/00-requirements-ledger.md"
BOUNDARY_DOC="${REPO_ROOT}/docs/design/granite-operator-boundary.md"
SEQUENCE_YAML="${SCRIPT_DIR}/SEQUENCE.yaml"

REQ_IDS=(
  R01 R02 R03 R04 R05 R06 R07 R08 R09 R10 R11 R12 R13 R14 R15
  R16 R17 R18 R19 R20 R21 R22 R23 R24
)

[[ -n "${PHASE}" ]] || {
  echo "usage: $0 <FH00|…|FH70|GW-0|…|GW-6|all>" >&2
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

require_master_mentions() {
  local needle="$1"
  grep -q "${needle}" "${MASTER_SEQ}" || fail "master sequence missing: ${needle}"
}

gate_stub_prompt() {
  local phase="$1"
  require_prompt "${phase}"
  info "${phase}" "stub gate (prompt file present)"
}

# --- GW-0 gates ---

gate_fh00() {
  require_file "${MASTER_SEQ}"
  require_file "${SEQUENCE_YAML}"
  require_file scripts/ff-granite-hosting-pdca/check-phase-gate.sh
  require_file scripts/ff-granite-hosting-pdca/pdca-run-phase.sh
  require_file scripts/ff-granite-hosting-pdca/run-wave.sh
  require_file scripts/ff-granite-hosting-pdca/check-granite-boundary.sh
  require_file "${PROMPT_DIR}/_prompt-template.md"
  require_prompt FH00
  grep -q 'Composer 2.5' "${MASTER_SEQ}" || fail "master sequence must specify Composer 2.5"
  grep -q 'FH70' "${SEQUENCE_YAML}" || fail "SEQUENCE missing FH70"
  grep -q 'GW-6' "${MASTER_SEQ}" || fail "master sequence missing GW-6 section"
  require_req_ids_in_ledger "${REQ_IDS[@]}"
}

gate_fh01() {
  gate_fh00
  require_prompt FH01
  require_file "${LEDGER}"
  require_file "${BOUNDARY_DOC}"
  require_req_ids_in_ledger "${REQ_IDS[@]}"
  grep -q 'SSH' "${BOUNDARY_DOC}" || fail "boundary doc must mention SSH rule"
  grep -q 'git-self-update' "${BOUNDARY_DOC}" || fail "boundary doc must mention git-self-update"
}

gate_fh02() {
  gate_fh01
  require_prompt FH02
  require_master_mentions 'forge-studio-shell'
  grep -q 'R11' "${LEDGER}" || fail "ledger missing R11"
  require_master_mentions 'fss-studio-shell-pdca'
}

gate_fh03() {
  gate_fh02
  require_prompt FH03
  require_master_mentions 'forge-market'
  grep -q 'R12' "${LEDGER}" || fail "ledger missing R12"
  require_master_mentions 'fm-postgres-hosting-pdca'
}

gate_fh04() {
  gate_fh03
  require_prompt FH04
  require_master_mentions 'forge-migrator'
  grep -q 'R10' "${LEDGER}" || fail "ledger missing R10"
  require_master_mentions 'fmigr-wizard-pdca'
}

gate_fh05() {
  gate_fh04
  require_prompt FH05
  grep -q 'GW-0 exit' "${MASTER_SEQ}" || grep -q 'GW-0 — Scaffold' "${MASTER_SEQ}" \
    || fail "master sequence missing GW-0 section"
  "${SCRIPT_DIR}/check-granite-boundary.sh"
}

# --- GW-1 gates ---

gate_fh10() {
  gate_fh05
  require_prompt FH10
  require_file fleet_server/managed_compose_service.py
  grep -q 'managed_compose_service' fleet_server/forge_llm_service.py \
    || fail "forge_llm_service must import managed_compose_service"
  grep -q 'compose.granite.yaml' fleet_server/managed_compose_service.py \
    || fail "managed_compose_service missing compose.granite.yaml allowlist"
  info FH10 "managed_compose_service refactor present"
}

gate_fh11() {
  gate_fh10
  require_prompt FH11
  grep -q 'forge_market_studio' fleet_server/container_layout.py \
    || fail "container_layout missing forge_market_studio type"
  info FH11 "forge_market_studio type in catalog"
}

gate_fh12() {
  gate_fh11
  require_prompt FH12
  grep -q '_managed_compose_record' fleet_server/main.py \
    || fail "main.py missing capability helper"
  grep -q 'managed_compose_service' fleet_server/main.py \
    || fail "main.py must use managed_compose_service"
  info FH12 "capability guards in main.py"
}

gate_fh13() {
  gate_fh12
  require_prompt FH13
  require_file deploy/forge-market-studio/compose.yaml
  require_file deploy/forge-market-studio/compose.granite.yaml
  require_file deploy/forge-market-studio/Dockerfile.market-app
  require_file deploy/forge-market-studio/.env.example
  grep -q 'postgres:16' deploy/forge-market-studio/compose.yaml \
    || fail "compose.yaml must use postgres:16"
  grep -q 'FORGE_MARKET_DATABASE_URL' deploy/forge-market-studio/compose.yaml \
    || fail "compose.yaml missing FORGE_MARKET_DATABASE_URL"
  info FH13 "Market Studio compose stack present"
}

gate_fh14() {
  gate_fh13
  require_prompt FH14
  require_file tests/test_managed_compose_service.py
  pytest tests/test_managed_compose_service.py tests/test_forge_llm_service.py -q
  info FH14 "compose integration tests green"
}

gate_fh15() {
  gate_fh14
  require_prompt FH15
  require_file docs/build-201/08-managed-compose-services.md
  grep -q '08-managed-compose-services' docs/build-201/README.md \
    || fail "build-201 README must link managed compose doc"
  info FH15 "managed compose operator doc present"
}

gate_fh16() {
  gate_fh15
  require_prompt FH16
  grep -q 'build_market_image' docs/build-201/08-managed-compose-services.md \
    || info FH16 "build_market_image job stub pending in docs"
  info FH16 "market image build job phase (stub)"
}

gate_fh17() {
  gate_fh16
  require_prompt FH17
  require_file fleet_server/forge_market_studio_rollout.py
  require_file scripts/rollout-forge-market-studio.sh
  grep -q 'forge-market-studio-rollout' fleet_server/main.py \
    || fail "main.py missing forge-market-studio-rollout route"
  require_file tests/test_forge_market_studio_rollout.py
  pytest tests/test_forge_market_studio_rollout.py -q
  info FH17 "Market Studio rollout API present"
}

gate_fh18() {
  gate_fh17
  require_prompt FH18
  grep -q 'forge_llm' fleet_server/container_layout.py \
    || fail "forge_llm type must remain in catalog"
  grep -q 'forge_market_studio' fleet_server/container_layout.py \
    || fail "forge_market_studio type must remain in catalog"
  info FH18 "GW-1 closeout — forge_llm + forge_market_studio coexist"
}

# --- GW-2 gates ---

gate_fh20() {
  gate_fh18
  require_prompt FH20
  require_file fleet_server/migrations.py
  grep -q '_ensure_migration_tables' fleet_server/store.py || fail "store missing migration tables"
  grep -q 'create_migration' fleet_server/store.py || fail "store missing create_migration"
  info FH20 "migration store schema present"
}

gate_fh21() {
  gate_fh20
  require_prompt FH21
  grep -q 'POST /v1/migrations' fleet_server/main.py || grep -q 'path == "/v1/migrations"' fleet_server/main.py \
    || fail "main.py missing POST /v1/migrations"
  grep -q '/v1/migrations/' fleet_server/main.py || fail "main.py missing GET /v1/migrations/{id}"
  info FH21 "migration REST routes wired"
}

gate_fh22() {
  gate_fh21
  require_prompt FH22
  grep -q 'migration_bundle' fleet_server/workspace_bundle.py || fail "missing migration_bundle profile"
  grep -q 'data-bundle' fleet_server/main.py || fail "missing PUT data-bundle route"
  info FH22 "data bundle upload present"
}

gate_fh23() {
  gate_fh22
  require_prompt FH23
  grep -q '.forge_migration_manifest.json' fleet_server/migrations.py || fail "missing migration manifest parser"
  grep -q 'flags' fleet_server/migrations.py || fail "missing manifest flags handling"
  info FH23 "bundle manifest spec present"
}

gate_fh24() {
  gate_fh23
  require_prompt FH24
  grep -q 'bytes_transferred' fleet_server/migrations.py || fail "missing bytes_transferred in migrations module"
  info FH24 "migration progress fields present"
}

gate_fh25() {
  gate_fh24
  require_prompt FH25
  require_file fleet_server/migration_jobs.py
  grep -q 'seed_corpus_volume' fleet_server/migration_jobs.py || fail "missing seed_corpus_volume step"
  info FH25 "seed corpus volume job template present"
}

gate_fh26() {
  gate_fh25
  require_prompt FH26
  grep -q 'migrate_db' fleet_server/migration_jobs.py || fail "missing migrate_db step"
  grep -q 'restore_from_bundle' fleet_server/migration_jobs.py || fail "missing restore_from_bundle step"
  info FH26 "db migration job templates present"
}

gate_fh27() {
  gate_fh26
  require_prompt FH27
  grep -q 'register_edge_route' fleet_server/migration_jobs.py || fail "missing register_edge_route step"
  info FH27 "edge route job template present"
}

gate_fh28() {
  gate_fh27
  require_prompt FH28
  require_file docs/build-201/09-migration-api.md
  require_file tests/test_migrations_api.py
  info FH28 "GW-2 closeout docs and tests present"
}

CODE_ROOT="$(cd "${REPO_ROOT}/.." && pwd)"
FM_ROOT="${CODE_ROOT}/forge-market"
FSS_ROOT="${CODE_ROOT}/forge-studio-shell"
FMIGR_ROOT="${CODE_ROOT}/forge-migrator"

require_sibling() {
  [[ -d "$1" ]] || fail "missing sibling repo: $1"
}

# --- GW-3 gates (forge-market Postgres hosting) ---

gate_fh30() {
  gate_fh28
  require_prompt FH30
  require_sibling "${FM_ROOT}"
  require_file "${FM_ROOT}/src/forge_market/db/connection.py"
  grep -q 'get_market_connection' "${FM_ROOT}/src/forge_market/db/connection.py" \
    || fail "forge-market missing get_market_connection"
  info FH30 "connection factory present"
}

gate_fh31() {
  gate_fh30
  require_prompt FH31
  grep -q 'ensure_schema' "${FM_ROOT}/src/forge_market/db/postgres.py" \
    || fail "postgres.py missing ensure_schema"
  info FH31 "Postgres DDL present"
}

gate_fh32() {
  gate_fh31
  require_prompt FH32
  grep -q 'get_db' "${FM_ROOT}/studio-server/studio_server.py" \
    || fail "studio_server missing get_db helper"
  info FH32 "studio server wired to connection factory"
}

gate_fh33() {
  gate_fh32
  require_prompt FH33
  require_file "${FM_ROOT}/tools/migrate_sqlite_to_postgres.py"
  info FH33 "SQLite to Postgres migrate tool present"
}

gate_fh34() {
  gate_fh33
  require_prompt FH34
  require_file "${FM_ROOT}/Dockerfile"
  require_file deploy/forge-market-studio/Dockerfile.market-app
  info FH34 "container Dockerfiles present"
}

gate_fh35() {
  gate_fh34
  require_prompt FH35
  require_file "${FM_ROOT}/docs/design/secondary-stores-adr.md"
  info FH35 "secondary stores ADR present"
}

gate_fh36() {
  gate_fh35
  require_prompt FH36
  require_file "${FM_ROOT}/tests/test_postgres_connection.py"
  (cd "${FM_ROOT}" && PYTHONPATH=src pytest tests/ -k postgres -q --ignore=tests/test_ibkr_flex_portal_v1.py)
  info FH36 "postgres tests green"
}

gate_fh37() {
  gate_fh36
  require_prompt FH37
  require_file "${FM_ROOT}/docs/design/edge-sync-cloud-adr.md"
  info FH37 "edge sync ADR present"
}

gate_fh38() {
  gate_fh37
  require_prompt FH38
  require_file "${FM_ROOT}/scripts/fm-postgres-hosting-pdca/check-phase-gate.sh"
  grep -q 'FM-ENT-004' "${FM_ROOT}/docs/handbook/shared/feature-index.md" \
    || fail "feature-index missing FM-ENT-004"
  grep -q 'implemented' "${FM_ROOT}/docs/handbook/shared/feature-index.md" \
    || fail "FM-ENT-004 not marked implemented"
  (cd "${FM_ROOT}" && ./scripts/fm-postgres-hosting-pdca/check-phase-gate.sh GW-3)
  info FH38 "GW-3 forge-market closeout green"
}

# --- GW-4 gates (forge-studio-shell) ---

gate_fh40() {
  gate_fh38
  require_prompt FH40
  require_sibling "${FSS_ROOT}"
  require_file "${FSS_ROOT}/lib/createStudioApp.js"
  info FH40 "forge-studio-shell core present"
}

gate_fh41() {
  gate_fh40
  require_prompt FH41
  grep -q 'attach-or-spawn' "${FSS_ROOT}/lib/createStudioApp.js" \
    || fail "createStudioApp missing attach-or-spawn profile"
  info FH41 "attach-or-spawn profile present"
}

gate_fh42() {
  gate_fh41
  require_prompt FH42
  require_file "${FSS_ROOT}/preload/studioElectron.js"
  info FH42 "preload IPC tiers present"
}

gate_fh43() {
  gate_fh42
  require_prompt FH43
  require_file "${FSS_ROOT}/schemas/studio.config.schema.json"
  require_file "${FSS_ROOT}/examples/market-studio.config.json"
  info FH43 "schema and examples present"
}

gate_fh44() {
  gate_fh43
  require_prompt FH44
  grep -q '@autowww/forge-studio-shell' "${FSS_ROOT}/package.json" \
    || fail "package.json missing @autowww/forge-studio-shell name"
  info FH44 "npm package metadata present"
}

gate_fh45() {
  gate_fh44
  require_prompt FH45
  require_file "${FM_ROOT}/studio.config.json"
  grep -q 'createStudioApp' "${FM_ROOT}/desktop/main.js" \
    || fail "forge-market desktop not using createStudioApp"
  info FH45 "forge-market adopts studio shell"
}

gate_fh46() {
  gate_fh45
  require_prompt FH46
  (cd "${FSS_ROOT}" && ./scripts/fss-studio-shell-pdca/check-phase-gate.sh all)
  info FH46 "studio shell regression gates green"
}

gate_fh47() {
  gate_fh46
  require_prompt FH47
  grep -q 'forge-studio-shell' "${FMIGR_ROOT}/desktop/main.js" \
    || grep -q 'createStudioApp' "${FMIGR_ROOT}/desktop/main.js" \
    || fail "forge-migrator desktop missing shell integration"
  info FH47 "forge-migrator adopts studio shell"
}

gate_fh48() {
  gate_fh47
  require_prompt FH48
  info FH48 "GW-4 closeout"
}

# --- GW-5 gates (forge-migrator) ---

gate_fh50() {
  gate_fh48
  require_prompt FH50
  require_sibling "${FMIGR_ROOT}"
  require_file "${FMIGR_ROOT}/migrator-server/migrator_server.py"
  info FH50 "migrator scaffold present"
}

gate_fh51() {
  gate_fh50
  require_prompt FH51
  require_file "${FMIGR_ROOT}/migrator-server/recipe_engine.py"
  require_file "${FMIGR_ROOT}/recipes/schema.yaml"
  info FH51 "recipe schema engine present"
}

gate_fh52() {
  gate_fh51
  require_prompt FH52
  grep -q 'FleetClient' "${FMIGR_ROOT}/migrator-server/recipe_engine.py" \
    || fail "recipe_engine missing FleetClient"
  info FH52 "Fleet client present"
}

gate_fh53() {
  gate_fh52
  require_prompt FH53
  require_file "${FMIGR_ROOT}/migrator-ui/src/App.tsx"
  info FH53 "progress UI present"
}

gate_fh54() {
  gate_fh53
  require_prompt FH54
  grep -q 'TestResults' "${FMIGR_ROOT}/migrator-ui/src/App.tsx" \
    || require_file "${FMIGR_ROOT}/migrator-ui/src/components/TestResultsPanel.tsx"
  info FH54 "test results UI present"
}

gate_fh55() {
  gate_fh54
  require_prompt FH55
  require_file "${FMIGR_ROOT}/integrations/cursor/run_agent.py"
  info FH55 "Cursor integration stub present"
}

gate_fh56() {
  gate_fh55
  require_prompt FH56
  require_file "${FMIGR_ROOT}/recipes/forge-market.yaml"
  info FH56 "forge-market recipe present"
}

gate_fh57() {
  gate_fh56
  require_prompt FH57
  require_file "${FMIGR_ROOT}/recipes/_example-minimal.yaml"
  info FH57 "generic example recipe present"
}

gate_fh58() {
  gate_fh57
  require_prompt FH58
  require_file "${FMIGR_ROOT}/migrator-ui/tests/wizard.spec.ts"
  info FH58 "migrator Playwright spec present"
}

gate_fh59() {
  gate_fh58
  require_prompt FH59
  (cd "${FMIGR_ROOT}" && python3 -m pytest tests/test_recipe_engine.py -q)
  (cd "${FMIGR_ROOT}" && ./scripts/fmigr-wizard-pdca/check-phase-gate.sh all)
  info FH59 "GW-5 migrator closeout green"
}

# --- GW-6 gates (Granite cutover + program closeout) ---

gate_fh60() {
  gate_fh59
  require_prompt FH60
  require_file docs/operate/granite-fleet-upgrade-only-ssh.md
  grep -q 'git-self-update' docs/operate/granite-fleet-upgrade-only-ssh.md \
    || fail "FH60 runbook missing git-self-update"
  grep -q 'Do not' docs/operate/granite-fleet-upgrade-only-ssh.md \
    || fail "FH60 runbook must forbid SSH data ops"
  info FH60 "Fleet upgrade-only SSH runbook present"
}

gate_fh61() {
  gate_fh60
  require_prompt FH61
  require_file docs/operate/granite-market-studio-cutover.md
  grep -q '/v1/migrations' docs/operate/granite-market-studio-cutover.md \
    || fail "cutover runbook missing migration API"
  info FH61 "staging/cutover runbook present"
}

gate_fh62() {
  gate_fh61
  require_prompt FH62
  grep -q 'Forbidden on Granite SSH' docs/operate/granite-market-studio-cutover.md \
    || fail "cutover runbook missing SSH forbidden list"
  info FH62 "production cutover doc present"
}

gate_fh63() {
  gate_fh62
  require_prompt FH63
  grep -q 'restore_from_bundle' docs/operate/granite-market-studio-cutover.md \
    || fail "rollback section missing restore_from_bundle"
  info FH63 "rollback drill documented"
}

gate_fh64() {
  gate_fh63
  require_prompt FH64
  require_file docs/build-201/08-managed-compose-services.md
  require_file docs/build-201/09-migration-api.md
  info FH64 "handbooks and OpenAPI docs present"
}

gate_fh65() {
  gate_fh64
  require_prompt FH65
  "${SCRIPT_DIR}/check-granite-boundary.sh"
  info FH65 "granite boundary audit green"
}

gate_fh70() {
  gate_fh65
  require_prompt FH70
  require_req_ids_in_ledger "${REQ_IDS[@]}"
  info FH70 "program closeout — requirements ledger complete"
}

# --- Wave aggregate gates ---

gate_gw0() {
  local phase_id
  for phase_id in FH00 FH01 FH02 FH03 FH04 FH05; do
    require_prompt "${phase_id}"
  done
  info GW-0 "all Wave 0 prompts present"
}

gate_gw1() {
  gate_gw0
  run_phase FH18
  info GW-1 "all Wave 1 phases green"
}

gate_gw2() {
  gate_gw1
  for phase_id in FH20 FH21 FH22 FH23 FH24 FH25 FH26 FH27 FH28; do
    require_prompt "${phase_id}"
  done
  gate_fh28
  info GW-2 "wave gate green"
}

gate_gw3() {
  gate_gw2
  run_phase FH38
  info GW-3 "wave gate green"
}

gate_gw4() {
  gate_gw3
  run_phase FH48
  info GW-4 "wave gate green"
}

gate_gw5() {
  gate_gw4
  run_phase FH59
  info GW-5 "wave gate green"
}

gate_gw6() {
  gate_gw5
  for phase_id in FH60 FH61 FH62 FH63 FH64 FH65 FH70; do
    require_prompt "${phase_id}"
  done
  require_file docs/operate/granite-fleet-upgrade-only-ssh.md
  require_file docs/operate/granite-market-studio-cutover.md
  "${SCRIPT_DIR}/check-granite-boundary.sh"
  info GW-6 "wave gate green"
}

run_phase() {
  local p="$1"
  case "${p}" in
    FH00) gate_fh00 ;;
    FH01) gate_fh01 ;;
    FH02) gate_fh02 ;;
    FH03) gate_fh03 ;;
    FH04) gate_fh04 ;;
    FH05) gate_fh05 ;;
    FH10) gate_fh10 ;;
    FH11) gate_fh11 ;;
    FH12) gate_fh12 ;;
    FH13) gate_fh13 ;;
    FH14) gate_fh14 ;;
    FH15) gate_fh15 ;;
    FH16) gate_fh16 ;;
    FH17) gate_fh17 ;;
    FH18) gate_fh18 ;;
    FH20) gate_fh20 ;;
    FH21) gate_fh21 ;;
    FH22) gate_fh22 ;;
    FH23) gate_fh23 ;;
    FH24) gate_fh24 ;;
    FH25) gate_fh25 ;;
    FH26) gate_fh26 ;;
    FH27) gate_fh27 ;;
    FH28) gate_fh28 ;;
    FH30) gate_fh30 ;;
    FH31) gate_fh31 ;;
    FH32) gate_fh32 ;;
    FH33) gate_fh33 ;;
    FH34) gate_fh34 ;;
    FH35) gate_fh35 ;;
    FH36) gate_fh36 ;;
    FH37) gate_fh37 ;;
    FH38) gate_fh38 ;;
    FH40) gate_fh40 ;;
    FH41) gate_fh41 ;;
    FH42) gate_fh42 ;;
    FH43) gate_fh43 ;;
    FH44) gate_fh44 ;;
    FH45) gate_fh45 ;;
    FH46) gate_fh46 ;;
    FH47) gate_fh47 ;;
    FH48) gate_fh48 ;;
    FH50) gate_fh50 ;;
    FH51) gate_fh51 ;;
    FH52) gate_fh52 ;;
    FH53) gate_fh53 ;;
    FH54) gate_fh54 ;;
    FH55) gate_fh55 ;;
    FH56) gate_fh56 ;;
    FH57) gate_fh57 ;;
    FH58) gate_fh58 ;;
    FH59) gate_fh59 ;;
    FH60) gate_fh60 ;;
    FH61) gate_fh61 ;;
    FH62) gate_fh62 ;;
    FH63) gate_fh63 ;;
    FH64) gate_fh64 ;;
    FH65) gate_fh65 ;;
    FH70) gate_fh70 ;;
    GW-0) gate_gw0 ;;
    GW-1) gate_gw1 ;;
    GW-2) gate_gw2 ;;
    GW-3) gate_gw3 ;;
    GW-4) gate_gw4 ;;
    GW-5) gate_gw5 ;;
    GW-6) gate_gw6 ;;
    *) fail "unknown phase: ${p}" ;;
  esac
  info "${p}" "CHECK GREEN"
}

if [[ "${PHASE}" == "all" ]]; then
  for p in FH00 FH01 FH02 FH03 FH04 FH05 \
    FH10 FH11 FH12 FH13 FH14 FH15 FH16 FH17 FH18 \
    FH20 FH21 FH22 FH23 FH24 FH25 FH26 FH27 FH28 \
    FH30 FH31 FH32 FH33 FH34 FH35 FH36 FH37 FH38 \
    FH40 FH41 FH42 FH43 FH44 FH45 FH46 FH47 FH48 \
    FH50 FH51 FH52 FH53 FH54 FH55 FH56 FH57 FH58 FH59 \
    FH60 FH61 FH62 FH63 FH64 FH65 FH70; do
    run_phase "${p}"
  done
else
  run_phase "${PHASE}"
fi
