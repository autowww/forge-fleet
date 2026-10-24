#!/usr/bin/env bash
# Local FMSBench entrypoint. Does not install Docker or change host services.
set -euo pipefail
cd "$(dirname "$0")"
command -v flock >/dev/null || { echo 'ERROR: flock from util-linux is required to lock the work directory.' >&2; exit 2; }
mkdir -p work results baselines
exec 9>work/.fmsbench.lock
if ! flock -n 9; then
  echo 'ERROR: another FMSBench run holds this work directory (work/.fmsbench.lock). Wait for that run to finish.' >&2
  exit 2
fi

label="${FMSBENCH_LABEL:-$(hostname -s)}"
args=("$@")
if [[ ${#args[@]} -ge 1 && "${args[0]}" == "--label" ]]; then
  if [[ ${#args[@]} -lt 2 ]]; then
    echo 'ERROR: --label requires a node name' >&2
    exit 2
  fi
  label="${args[1]}"
  args=("${args[@]:2}")
fi
profile="smoke"
for ((i=0; i<${#args[@]}; i++)); do
  if [[ "${args[$i]}" == "--profile" ]]; then
    if [[ $((i+1)) -ge ${#args[@]} ]]; then
      echo 'ERROR: --profile requires a value' >&2
      exit 2
    fi
    profile="${args[$((i+1))]}"
  elif [[ "${args[$i]}" == --profile=* ]]; then
    profile="${args[$i]#--profile=}"
  fi
done

export FMSBENCH_PROJECT="$(python3 -c 'from preflight import project_name; from pathlib import Path; print(project_name(Path(".").resolve()))')"
python3 preflight.py --work work --profile "$profile" --report results/preflight-last.json

if [[ ! -f .env ]]; then
  umask 077
  PASS="$(python3 - <<'PY'
import secrets
print(secrets.token_hex(24))
PY
)"
  printf 'FMSBENCH_PASSWORD=%s\n' "$PASS" > .env
fi
chmod 600 .env

docker compose build runner
docker compose up -d --wait postgres
exec docker compose run --rm runner run --node "$label" "${args[@]}"
