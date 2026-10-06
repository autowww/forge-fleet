#!/usr/bin/env bash
# Ensure postgresql.conf includes PG-A tuning file (official postgres:16 image).
set -euo pipefail
PG_CONTAINER="${FORGE_MARKET_PG_CONTAINER:-forge-market-postgres}"
MARK="${PGDATA_CONF_MARK:-include_if_exists = '/etc/postgresql/conf.d/99-forge-market-tuning.conf'}"
docker exec "$PG_CONTAINER" bash -lc "
  if ! grep -qF '/etc/postgresql/conf.d/99-forge-market-tuning.conf' /var/lib/postgresql/data/postgresql.conf; then
    echo \"$MARK\" >> /var/lib/postgresql/data/postgresql.conf
  fi
"
echo "ok: postgresql.conf includes PG-A tuning path"
