#!/usr/bin/env bash
# Root worker: apply queued forge-fleet apt upgrade signals (runs every minute via systemd timer).
set -euo pipefail

FLEET_LIB="${FLEET_LIB:-/usr/lib/forge-fleet}"
LOG_TAG="forge-fleet-apt-upgrade"
MAX_AGE_SEC="${FLEET_UPGRADE_SIGNAL_MAX_AGE_SEC:-1800}"

log() { echo "${LOG_TAG}: $*"; }

_refresh_forge_apt_keyring() {
  local base="${FORGE_APT_BASE_URL:-https://packages.forgesdlc.com/fleet/ubuntu}"
  local keyring="/usr/share/keyrings/forge-fleet-archive-keyring.gpg"
  [[ -f /etc/apt/sources.list.d/forge-fleet.list ]] || return 0
  if ! curl -fsSL "${base}/gpg.key" | gpg --batch --yes --dearmor -o "$keyring" 2>/dev/null; then
    log "WARN: could not refresh ${keyring} from CDN"
    return 0
  fi
  chmod a+r "$keyring" 2>/dev/null || true
}

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
    # Exit 0 when the signal is stale so `if _stale` removes it.
    sys.exit(0 if age > max_age else 1)
except Exception:
    sys.exit(1)
PY
}

_write_failure_result() {
  local out_dir="$1" doc="$2" err="$3" detail="$4"
  local result_file="${out_dir}/upgrade-result.json"
  mkdir -p "$(dirname "$result_file")"
  python3 - "$result_file" "$doc" "$err" "$detail" <<'PY'
import json, sys
from datetime import datetime, timezone
out, doc_raw, err, detail = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
doc = json.loads(doc_raw)
payload = {
    "ok": False,
    "error": err,
    "detail": detail,
    "completed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "request_id": doc.get("request_id"),
    "package": doc.get("package"),
}
open(out, "w", encoding="utf-8").write(json.dumps(payload, indent=2) + "\n")
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
  local inst_before inst_after cand
  inst_before="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("installed_version_before",""))' "$doc")"
  _refresh_forge_apt_keyring
  rm -f /var/lib/apt/lists/packages.forgesdlc.com_fleet_ubuntu_dists_noble_* 2>/dev/null || true
  if ! apt-get update -qq; then
    log "apt-get update failed"
    _write_failure_result "$user_data_dir" "$doc" "apt_update_failed" "apt-get update failed"
    rm -f "$signal_file"
    return 0
  fi
  if ! apt-get install -y "$package"; then
    log "apt-get install failed for $package"
    _write_failure_result "$user_data_dir" "$doc" "apt_install_failed" "apt-get install failed"
    rm -f "$signal_file"
    return 0
  fi
  inst_after="$(dpkg-query -W -f='${Version}' "$package" 2>/dev/null || true)"
  cand="$(apt-cache policy "$package" 2>/dev/null | awk '/^[[:space:]]+candidate:/ {print $2; exit}')"
  if [[ -n "$cand" && "$cand" != "(none)" && -n "$inst_after" ]] \
    && dpkg --compare-versions "$cand" gt "$inst_after" 2>/dev/null; then
    log "apt candidate ${cand} newer than installed ${inst_after} — fix forge-fleet apt source (noble suite)"
    _write_failure_result "$user_data_dir" "$doc" "apt_no_upgrade" \
      "installed=${inst_after} apt candidate=${cand}; check /etc/apt/sources.list.d/forge-fleet.list"
    rm -f "$signal_file"
    return 0
  fi

  if [[ "$channel" == "apt_user" && -n "$username" ]]; then
    local uid runtime
    uid="$(id -u "$username")"
    runtime="/run/user/${uid}"
    runuser -u "$username" -- env XDG_RUNTIME_DIR="$runtime" DBUS_SESSION_BUS_ADDRESS="unix:path=${runtime}/bus" land-fleet setup-user || true
    runuser -u "$username" -- env XDG_RUNTIME_DIR="$runtime" DBUS_SESSION_BUS_ADDRESS="unix:path=${runtime}/bus" systemctl --user restart forge-fleet.service || true
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
  log "upgrade complete package=${inst_after:-unknown} -> $result_file"
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
