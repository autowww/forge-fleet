#!/usr/bin/env bash
# Fleet admin: backfill pattern cell rollup tables in Market Studio Postgres.
# Trigger via POST /v1/admin/forge-market-pattern-rollups-backfill (no SSH).
set -eEuo pipefail

FLEET_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FORGE_MARKET_ENV="${FORGE_MARKET_ENV:-prod}"
FORGE_MARKET_ROOT="${FORGE_MARKET_ROOT:-}"
COMPOSE_FILES="${FORGE_MARKET_COMPOSE_FILES:-compose.granite.yaml}"
FORGE_MARKET_PATTERN_ROLLUPS_TICKERS="${FORGE_MARKET_PATTERN_ROLLUPS_TICKERS:-}"
FORGE_MARKET_PATTERN_ROLLUPS_INTERVALS="${FORGE_MARKET_PATTERN_ROLLUPS_INTERVALS:-}"
FORGE_MARKET_PATTERN_ROLLUPS_LIMIT="${FORGE_MARKET_PATTERN_ROLLUPS_LIMIT:-0}"
FORGE_MARKET_PATTERN_ROLLUPS_CHECKPOINT="${FORGE_MARKET_PATTERN_ROLLUPS_CHECKPOINT:-/app/data/.pattern_cell_rollups_backfill.json}"
FORGE_MARKET_PATTERN_ROLLUPS_DRY_RUN="${FORGE_MARKET_PATTERN_ROLLUPS_DRY_RUN:-0}"

log() { printf 'backfill-forge-market-pattern-rollups: %s\n' "$*"; }
die() { log "ERROR: $*"; exit 1; }

_rollout_python() {
  (cd "$FLEET_ROOT" && python3 -c "$1")
}

if [[ -z "${MARKET_STUDIO_ROOT:-}" ]]; then
  MARKET_STUDIO_ROOT="$(_rollout_python "
from pathlib import Path
from fleet_server.market_studio_rollout_env import compose_root_for_env
import os
print(compose_root_for_env(Path('${FLEET_ROOT}'), os.environ.get('FORGE_MARKET_ENV','prod')))
")"
fi
export MARKET_STUDIO_ROOT

resolve_forge_market_root() {
  if [[ -n "${FORGE_MARKET_ROOT}" && -f "${FORGE_MARKET_ROOT}/studio-server/studio_server.py" ]]; then
    printf '%s' "$FORGE_MARKET_ROOT"
    return 0
  fi
  local candidate
  for candidate in \
    "/home/administrator/forge-market" \
    "$FLEET_ROOT/../forge-market" \
    "$HOME/forge-market" \
    "$HOME/Code/forge-market"; do
    if [[ -f "$candidate/studio-server/studio_server.py" ]]; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

compose() {
  if docker compose version &>/dev/null; then
    docker compose "$@"
  elif command -v docker-compose &>/dev/null; then
    docker-compose "$@"
  else
    log "ERROR: docker compose not available"
    return 127
  fi
}

compose_file_args() {
  local -n out=$1
  out=(-f compose.yaml)
  if [[ -n "$COMPOSE_FILES" ]]; then
    IFS=',' read -ra overlays <<<"$COMPOSE_FILES"
    for ov in "${overlays[@]}"; do
      ov="${ov#"${ov%%[![:space:]]*}"}"
      ov="${ov%"${ov##*[![:space:]]}"}"
      [[ -n "$ov" ]] || continue
      [[ -f "$ov" ]] || die "compose overlay missing: $ov"
      out+=(-f "$ov")
    done
  fi
}

ensure_paths() {
  [[ -f "$MARKET_STUDIO_ROOT/compose.yaml" ]] || die "missing $MARKET_STUDIO_ROOT/compose.yaml"
  FORGE_MARKET_ROOT="$(resolve_forge_market_root)" || die "forge-market checkout missing (set FORGE_MARKET_ROOT)"
  export FORGE_MARKET_ROOT
  local script="${FORGE_MARKET_ROOT}/tools/backfill_pattern_cell_rollups.py"
  [[ -f "$script" ]] || die "missing ${script} — deploy forge-market with m043 first"
  log "using forge-market root $FORGE_MARKET_ROOT"
}

main() {
  ensure_paths
  cd "$MARKET_STUDIO_ROOT"
  local -a files
  compose_file_args files

  local -a cmd=(python tools/backfill_pattern_cell_rollups.py)
  cmd+=(--checkpoint "$FORGE_MARKET_PATTERN_ROLLUPS_CHECKPOINT")
  if [[ -n "$FORGE_MARKET_PATTERN_ROLLUPS_TICKERS" ]]; then
    cmd+=(--tickers "$FORGE_MARKET_PATTERN_ROLLUPS_TICKERS")
  fi
  if [[ -n "$FORGE_MARKET_PATTERN_ROLLUPS_INTERVALS" ]]; then
    cmd+=(--intervals "$FORGE_MARKET_PATTERN_ROLLUPS_INTERVALS")
  fi
  if [[ "$FORGE_MARKET_PATTERN_ROLLUPS_LIMIT" =~ ^[0-9]+$ ]] && [[ "$FORGE_MARKET_PATTERN_ROLLUPS_LIMIT" -gt 0 ]]; then
    cmd+=(--limit "$FORGE_MARKET_PATTERN_ROLLUPS_LIMIT")
  fi
  if [[ "$FORGE_MARKET_PATTERN_ROLLUPS_DRY_RUN" == "1" ]]; then
    cmd+=(--dry-run)
  fi

  log "starting pattern cell rollup backfill (env=${FORGE_MARKET_ENV})"
  log "command: ${cmd[*]}"
  compose "${files[@]}" run --rm -T --no-deps market-app "${cmd[@]}"
  log "pattern cell rollup backfill complete"
}

main "$@"
