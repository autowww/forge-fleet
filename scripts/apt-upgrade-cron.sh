#!/usr/bin/env bash
# Root worker: apply queued forge-fleet apt upgrade signals (runs every minute via systemd timer).
set -euo pipefail

FLEET_LIB="${FLEET_LIB:-/usr/lib/forge-fleet}"
LOG_TAG="forge-fleet-apt-upgrade"
MAX_AGE_SEC="${FLEET_UPGRADE_SIGNAL_MAX_AGE_SEC:-300}"

log() { echo "${LOG_TAG}: $*"; }

_stale() {
  local file="$1"
  python3 - "$file" "$MAX_AGE_SEC" <<'PY'
import json, sys
from datetime import datetime, timezone
path, max_age = sys.argv[1], int(sys.argv[2])
try:
    doc = json.loads(open(path, encoding="utf-8").read())
    ts = str(doc.get("requested_at") or "")
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    age = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()
    sys.exit(0 if age <= max_age else 1)
except Exception:
    sys.exit(1)
PY
}

_process_signal() {
  local signal_file="$1"
  local doc
  doc="$(cat "$signal_file")"
  local package username user_data_dir channel
  package="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("package",""))' "$doc")"
  username="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("username",""))' "$doc")"
  user_data_dir="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("user_data_dir",""))' "$doc")"
  channel="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("install_channel",""))' "$doc")"
  [[ -n "$package" ]] || { log "invalid signal (no package): $signal_file"; rm -f "$signal_file"; return 0; }

  log "applying apt upgrade package=$package user=$username"
  apt-get update -qq
  apt-get install -y "$package"

  if [[ "$channel" == "apt_user" && -n "$username" ]]; then
    runuser -u "$username" -- land-fleet setup-user || true
    runuser -u "$username" -- systemctl --user restart forge-fleet.service || true
  elif [[ "$channel" == "apt_system" ]]; then
    systemctl restart forge-fleet.service || true
  fi

  local result_file="${user_data_dir}/upgrade-result.json"
  mkdir -p "$(dirname "$result_file")"
  python3 - "$result_file" "$doc" <<'PY'
import json, sys
from datetime import datetime, timezone
out = sys.argv[1]
doc = json.loads(sys.argv[2])
payload = {
    "ok": True,
    "completed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "request_id": doc.get("request_id"),
    "package": doc.get("package"),
}
open(out, "w", encoding="utf-8").write(json.dumps(payload, indent=2) + "\n")
PY
  rm -f "$signal_file"
  log "upgrade complete -> $result_file"
}

scan_user_signals() {
  local u home signal
  for home in /home/*; do
    [[ -d "$home" ]] || continue
    signal="${home}/.local/state/forge-fleet/upgrade-request.json"
    [[ -f "$signal" ]] || continue
    if _stale "$signal"; then
      log "removing stale user signal $signal"
      rm -f "$signal"
      continue
    fi
    _process_signal "$signal"
  done
}

scan_system_signal() {
  local signal="/var/lib/forge-fleet/upgrade-request.json"
  [[ -f "$signal" ]] || return 0
  if _stale "$signal"; then
    log "removing stale system signal $signal"
    rm -f "$signal"
    return 0
  fi
  _process_signal "$signal"
}

scan_user_signals
scan_system_signal
