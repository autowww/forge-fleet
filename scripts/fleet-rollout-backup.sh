#!/usr/bin/env bash
# Generic pg_dump backup for Fleet rollouts (pg_dump_docker kind).
set -euo pipefail

DEST="${1:-}"
PG_CONTAINER="${FORGE_MARKET_PG_CONTAINER:-forge-market-postgres}"
PG_USER="${POSTGRES_USER:-forge_market}"
PG_DB="${POSTGRES_DB:-forge_market}"

[[ -n "$DEST" ]] || {
  echo "usage: fleet-rollout-backup.sh <output.dump>" >&2
  exit 1
}

mkdir -p "$(dirname "$DEST")"

if ! docker inspect "$PG_CONTAINER" &>/dev/null; then
  echo "postgres container missing: $PG_CONTAINER" >&2
  exit 1
fi

docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -Fc "$PG_DB" >"$DEST"

verify_backup_dump() {
  local dump="$1"
  if command -v pg_restore >/dev/null 2>&1 && pg_restore --list "$dump" >/dev/null 2>&1; then
    return 0
  fi
  local remote="/tmp/fleet-rollout-backup-verify-$$.dump"
  docker cp "$dump" "${PG_CONTAINER}:${remote}"
  if docker exec "$PG_CONTAINER" pg_restore --list "$remote" >/dev/null 2>&1; then
    docker exec "$PG_CONTAINER" rm -f "$remote"
    return 0
  fi
  docker exec "$PG_CONTAINER" rm -f "$remote" 2>/dev/null || true
  return 1
}

if ! verify_backup_dump "$DEST"; then
  echo "backup verification failed: pg_restore --list" >&2
  rm -f "$DEST"
  exit 1
fi

bytes="$(wc -c <"$DEST" | tr -d ' ')"
echo "backup ok path=$DEST bytes=$bytes verified=true"
