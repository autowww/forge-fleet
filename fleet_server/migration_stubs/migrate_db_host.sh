#!/bin/sh
# Host wrapper: stop recipe compose service before migrate_db frees Postgres slots.
# Args: COMPOSE_ROOT COMPOSE_SERVICE COMPOSE_FILES CSV (or "-" to skip) … docker run …
set -eu

ROOT="${1:-}"
SERVICE="${2:-}"
FILES="${3:-}"
shift 3

if [ -n "${ROOT}" ] && [ "${ROOT}" != "-" ] && [ -d "${ROOT}" ]; then
  cd "${ROOT}"
  if [ -n "${SERVICE}" ] && [ "${SERVICE}" != "-" ]; then
    if [ -n "${FILES}" ] && [ "${FILES}" != "-" ]; then
      COMPOSE_ARGS=""
      OLDIFS=${IFS}
      IFS=,
      for f in ${FILES}; do
        COMPOSE_ARGS="${COMPOSE_ARGS} -f ${f}"
      done
      IFS=${OLDIFS}
      # shellcheck disable=SC2086
      docker compose ${COMPOSE_ARGS} --project-directory "${ROOT}" stop "${SERVICE}" 2>/dev/null || true
    else
      docker compose --project-directory "${ROOT}" stop "${SERVICE}" 2>/dev/null || true
    fi
    sleep 2
  fi
fi

exec "$@"
