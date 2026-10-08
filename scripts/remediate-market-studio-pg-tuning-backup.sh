#!/usr/bin/env bash
# Fix Granite market-studio postgres-tuning bind mount + take a verified pg_dump (Fleet API only).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRETS="${FORGE_CERTIFICATOR_ENV_FILE:-$ROOT/../forge-certificators/example-banks/forge-certificator-secrets.env}"
if [[ -f "$SECRETS" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$SECRETS"
  set +a
fi

BASE="${FORGE_FLEET_BASE_URL:-}"
TOK="${FORGE_FLEET_BEARER_TOKEN:-}"
DEPLOY="${REMEDIATE_STUDIO_ROOT:-/home/administrator/.local/share/forge-fleet/deploy/forge-market-studio}"
BACKUP_DIR="${REMEDIATE_BACKUP_DIR:-/home/administrator/.local/state/forge-fleet/backups/market-studio}"

[[ -n "$BASE" && -n "$TOK" ]] || {
  echo "set FORGE_FLEET_BASE_URL and FORGE_FLEET_BEARER_TOKEN" >&2
  exit 1
}

log() { printf 'remediate-pg-tuning-backup: %s\n' "$*"; }

submit_job() {
  local body="$1"
  curl -fsS -X POST "${BASE}/v1/jobs" \
    -H "Authorization: Bearer ${TOK}" \
    -H "Content-Type: application/json" \
    -d "$body"
}

poll_job() {
  local jid="$1"
  local deadline=$((SECONDS + 1200))
  while (( SECONDS < deadline )); do
    local st
    st="$(curl -fsS "${BASE}/v1/jobs/${jid}" -H "Authorization: Bearer ${TOK}")"
    local status
    status="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))' <<<"$st")"
    if [[ "$status" == "completed" ]]; then
      echo "$st"
      return 0
    fi
    if [[ "$status" == "failed" ]]; then
      echo "$st" >&2
      return 1
    fi
    sleep 8
  done
  echo "job ${jid} timed out" >&2
  return 1
}

FIX_SH="$(cat <<'EOS'
set -euo pipefail
cd /work
if [ -d postgres-tuning.conf ]; then rm -rf postgres-tuning.conf; echo removed_mistaken_tuning_dir; fi
test -f postgres-tuning.conf.disabled
if grep -q '^FORGE_MARKET_PG_TUNING_CONF=' .env 2>/dev/null; then
  sed -i 's|^FORGE_MARKET_PG_TUNING_CONF=.*|FORGE_MARKET_PG_TUNING_CONF=./postgres-tuning.conf.disabled|' .env
else
  echo 'FORGE_MARKET_PG_TUNING_CONF=./postgres-tuning.conf.disabled' >> .env
fi
grep '^FORGE_MARKET_PG_TUNING_CONF=' .env
VOL=forge_market_studio_pgdata
docker run --rm -v "${VOL}:/var/lib/postgresql/data" alpine:3.20 sh -c \
  "sed -i '/99-forge-market-tuning/d' /var/lib/postgresql/data/postgresql.conf || true"
if [ -f compose.granite.yaml ]; then
  docker compose -f compose.yaml -f compose.granite.yaml up -d --force-recreate postgres
else
  docker compose -f compose.yaml up -d --force-recreate postgres
fi
for _ in $(seq 1 40); do
  if docker exec forge-market-postgres pg_isready -U forge_market -d forge_market 2>/dev/null; then
    echo pg_ready
    break
  fi
  sleep 3
done
if [ -f compose.granite.yaml ]; then
  docker compose -f compose.yaml -f compose.granite.yaml up -d market-app
else
  docker compose -f compose.yaml up -d market-app
fi
EOS
)"

BACKUP_SH="$(cat <<EOS
set -euo pipefail
PG_CONTAINER=forge-market-postgres
PG_USER=forge_market
PG_DB=forge_market
mkdir -p /backups
ts=\$(date -u +%Y%m%dT%H%M%SZ)
dest=/backups/\${ts}-post-m059-manual.dump
docker exec \"\$PG_CONTAINER\" pg_dump -U \"\$PG_USER\" -Fc \"\$PG_DB\" >\"\$dest\"
docker exec -i \"\$PG_CONTAINER\" pg_restore --list <\"\$dest\" >/dev/null
bytes=\$(wc -c <\"\$dest\" | tr -d ' ')
echo backup_ok path=\$dest bytes=\$bytes
ls -la \"\$dest\"
EOS
)"

log "submit fix+recreate postgres job"
export FIX_SH DEPLOY
FIX_BODY="$(python3 - <<PY
import json, os
sh = os.environ["FIX_SH"]
deploy = os.environ["DEPLOY"]
argv = [
    "docker", "run", "--rm",
    "-v", "/var/run/docker.sock:/var/run/docker.sock",
    "-v", f"{deploy}:/work",
    "-w", "/work",
    "docker:27-cli",
    "sh", "-c", sh,
]
print(json.dumps({
    "kind": "docker_argv",
    "argv": argv,
    "session_id": "remediate-pg-tuning",
    "meta": {"container_class": "market_studio_remediate", "workload_label": "pg-tuning-mount-fix"},
}))
PY
)"
FIX_JOB="$(submit_job "$FIX_BODY")"
FIX_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$FIX_JOB")"
log "fix job id=$FIX_ID"
poll_job "$FIX_ID" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("stdout","")[-2000:]); print("exit", d.get("exit_code"))'

log "submit manual backup job"
export DEPLOY BACKUP_DIR BACKUP_SH
BACKUP_BODY="$(python3 - <<'PY'
import json, os
sh = os.environ["BACKUP_SH"]
argv = [
    "docker", "run", "--rm",
    "-v", "/var/run/docker.sock:/var/run/docker.sock",
    "-v", os.environ["BACKUP_DIR"] + ":/backups",
    "docker:27-cli",
    "sh", "-c", sh,
]
print(json.dumps({
    "kind": "docker_argv",
    "argv": argv,
    "session_id": "remediate-pg-backup",
    "meta": {"container_class": "market_studio_remediate", "workload_label": "post-m059-manual-backup"},
}))
PY
)"
BACKUP_JOB="$(submit_job "$BACKUP_BODY")"
BACKUP_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$BACKUP_JOB")"
log "backup job id=$BACKUP_ID"
poll_job "$BACKUP_ID" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("stdout","")[-2000:]); print("exit", d.get("exit_code"))'

log "done"
