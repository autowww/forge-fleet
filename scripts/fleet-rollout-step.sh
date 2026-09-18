#!/usr/bin/env bash
# Generic Fleet rollout step/status helper. Source from service rollout scripts.
# Writes JSON status files consumed by fleet_server.rollout_status.

_FLEET_SERVICE_ID=""
_FLEET_LOG_PATH=""
_FLEET_STATUS_DIR="${FLEET_ROLLOUT_STATUS_DIR:-$HOME/.local/state/forge-fleet/rollout-status}"
_CURRENT_STEP=""

_fleet_status_file() {
  printf '%s/%s.json' "${_FLEET_STATUS_DIR}" "${_FLEET_SERVICE_ID}"
}

_fleet_iso_now() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

_fleet_log_tail() {
  local n="${1:-80}"
  if [[ -n "${_FLEET_LOG_PATH}" && -f "${_FLEET_LOG_PATH}" ]]; then
    tail -n "$n" "${_FLEET_LOG_PATH}" 2>/dev/null || true
  fi
}

_fleet_write_status() {
  python3 - "$(_fleet_status_file)" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(json.loads(sys.stdin.read()), indent=2), encoding="utf-8")
PY
}

fleet_rollout_begin() {
  _FLEET_SERVICE_ID="$1"
  _FLEET_LOG_PATH="$2"
  mkdir -p "${_FLEET_STATUS_DIR}"
  local now
  now="$(_fleet_iso_now)"
  printf '%s' "{
  \"service_id\": \"${_FLEET_SERVICE_ID}\",
  \"maintenance\": true,
  \"failed\": false,
  \"started_at\": \"${now}\",
  \"updated_at\": \"${now}\",
  \"current_step\": \"init\",
  \"current_step_label\": \"Starting rollout\",
  \"steps_done\": [],
  \"error\": \"\",
  \"log_tail\": \"\"
}" | _fleet_write_status
  _CURRENT_STEP="init"
}

fleet_rollout_step() {
  local step_id="$1"
  local label="${2:-$1}"
  local now prev
  now="$(_fleet_iso_now)"
  prev="${_CURRENT_STEP:-}"
  _CURRENT_STEP="$step_id"
  FLEET_STATUS_FILE="$(_fleet_status_file)" \
    FLEET_STEP_ID="$step_id" \
    FLEET_STEP_LABEL="$label" \
    FLEET_STEP_NOW="$now" \
    FLEET_STEP_PREV="$prev" \
    python3 - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["FLEET_STATUS_FILE"])
step_id = os.environ["FLEET_STEP_ID"]
label = os.environ["FLEET_STEP_LABEL"]
now = os.environ["FLEET_STEP_NOW"]
prev = os.environ.get("FLEET_STEP_PREV", "")

data: dict = {}
if path.is_file():
    data = json.loads(path.read_text(encoding="utf-8"))
else:
    data = {"service_id": "", "maintenance": True, "failed": False, "steps_done": []}

steps = list(data.get("steps_done") or [])
if prev and prev != step_id and prev not in steps:
    steps.append(prev)

data["maintenance"] = True
data["failed"] = False
data["current_step"] = step_id
data["current_step_label"] = label
data["updated_at"] = now
data["steps_done"] = steps
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(data, indent=2), encoding="utf-8")
PY
  printf 'fleet-rollout-step: %s — %s\n' "$step_id" "$label" >&2
}

fleet_rollout_done() {
  local status_file
  status_file="$(_fleet_status_file)"
  if [[ -f "$status_file" ]]; then
    rm -f "$status_file"
  fi
  _CURRENT_STEP=""
}

fleet_rollout_failed() {
  local step_id="${1:-${_CURRENT_STEP:-unknown}}"
  local reason="${2:-Rollout failed}"
  local now log_tail escaped_reason escaped_tail
  now="$(_fleet_iso_now)"
  log_tail="$(_fleet_log_tail 80)"
  FLEET_STATUS_FILE="$(_fleet_status_file)" \
    FLEET_FAILED_STEP="$step_id" \
    FLEET_FAILED_NOW="$now" \
    FLEET_FAILED_REASON="$reason" \
    FLEET_LOG_TAIL="$log_tail" \
    python3 - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["FLEET_STATUS_FILE"])
step_id = os.environ["FLEET_FAILED_STEP"]
now = os.environ["FLEET_FAILED_NOW"]
reason = os.environ["FLEET_FAILED_REASON"]
log_tail = os.environ.get("FLEET_LOG_TAIL", "")

data: dict = {}
if path.is_file():
    data = json.loads(path.read_text(encoding="utf-8"))
else:
    data = {"service_id": "", "steps_done": []}

steps = list(data.get("steps_done") or [])
prev = str(data.get("current_step") or "")
if prev and prev != step_id and prev not in steps:
    steps.append(prev)

data["maintenance"] = False
data["failed"] = True
data["failed_at"] = now
data["updated_at"] = now
data["failed_step"] = step_id
data["current_step"] = step_id
data["error"] = reason
data["log_tail"] = log_tail
data["steps_done"] = steps
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(data, indent=2), encoding="utf-8")
PY
  printf 'fleet-rollout-step: FAILED at %s — %s\n' "$step_id" "$reason" >&2
}
