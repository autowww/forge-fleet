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

if ! pg_restore --list "$DEST" >/dev/null 2>&1; then
  echo "backup verification failed: pg_restore --list" >&2
  rm -f "$DEST"
  exit 1
fi

bytes="$(wc -c <"$DEST" | tr -d ' ')"
echo "backup ok path=$DEST bytes=$bytes verified=true"
