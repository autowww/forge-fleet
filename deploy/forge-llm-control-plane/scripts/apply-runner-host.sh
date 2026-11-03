#!/usr/bin/env bash
# Apply configs/runner*.yaml to host Ollama (systemd user drop-in + optional model pull).
# Intended to run on Granite during control-plane rollout (not from gateway container).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

RUNNER_FILE="${FORGE_LLM_RUNNER_CONFIG:-}"
if [[ -z "$RUNNER_FILE" ]]; then
  for candidate in "$ROOT/configs/runner.yaml" "$ROOT/configs/runner.granite.yaml"; do
    if [[ -f "$candidate" ]]; then
      RUNNER_FILE="$candidate"
      break
    fi
  done
fi
[[ -n "$RUNNER_FILE" && -f "$RUNNER_FILE" ]] || {
  echo "apply-runner-host: no runner config found under $ROOT/configs/" >&2
  exit 1
}

APPLY_MODE="${FORGE_LLM_RUNNER_APPLY:-observe}"
# observe = log unit + models only; apply = write drop-in + pull missing models

log() { printf 'apply-runner-host: %s\n' "$*"; }

log "runner file: $RUNNER_FILE (mode=$APPLY_MODE)"

log "=== ollama.service (user) ==="
systemctl --user show ollama.service -p ActiveState -p SubState -p Environment 2>/dev/null || log "ollama.service not found"

log "=== ollama list ==="
ollama list 2>/dev/null || log "ollama list failed (daemon down?)"

DROPIN_DIR="${HOME}/.config/systemd/user/ollama.service.d"
DROPIN_FILE="$DROPIN_DIR/forge-llm-runner.conf"

render_dropin() {
  export APPLY_ROOT="$ROOT"
  export FORGE_LLM_RUNNER_CONFIG="$RUNNER_FILE"
  python3 - <<'PY'
import importlib.util
import os
import sys
import types
from pathlib import Path

root = Path(os.environ["APPLY_ROOT"])
gw = root / "apps" / "forge-gateway"
sys.path.insert(0, str(gw))
sys.modules.setdefault("runners", types.ModuleType("runners"))
for mod_name, rel in (("runners.base", "runners/base.py"), ("runners.loader", "runners/loader.py")):
    spec = importlib.util.spec_from_file_location(mod_name, gw / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
loader = sys.modules["runners.loader"]

loader.reset_runner_cache()
cfg = loader.load_runner_config(reload=True)
print(loader.render_systemd_dropin(cfg.runtime), end="")
PY
}

missing_models() {
  export APPLY_ROOT="$ROOT"
  export FORGE_LLM_RUNNER_CONFIG="$RUNNER_FILE"
  python3 - <<'PY'
import importlib.util
import os
import subprocess
import sys
import types
from pathlib import Path

root = Path(os.environ["APPLY_ROOT"])
gw = root / "apps" / "forge-gateway"
sys.path.insert(0, str(gw))
sys.modules.setdefault("runners", types.ModuleType("runners"))
for mod_name, rel in (("runners.base", "runners/base.py"), ("runners.loader", "runners/loader.py")):
    spec = importlib.util.spec_from_file_location(mod_name, gw / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
loader = sys.modules["runners.loader"]

loader.reset_runner_cache()
cfg = loader.load_runner_config(reload=True)
try:
    out = subprocess.check_output(["ollama", "list"], text=True, stderr=subprocess.DEVNULL)
except (subprocess.CalledProcessError, FileNotFoundError):
    out = ""
installed = {line.split()[0] for line in out.splitlines()[1:] if line.strip()}
for name in cfg.models:
    base = name.split(":")[0]
    if not any(m == name or m.startswith(base + ":") or m == base for m in installed):
        print(name)
PY
}

NEW_DROPIN="$(render_dropin)"
if [[ -z "${NEW_DROPIN//[$'\n\r\t ']/}" || "$NEW_DROPIN" == "[Service]" ]]; then
  log "runtime block empty — no drop-in changes"
else
  mkdir -p "$DROPIN_DIR"
  if [[ -f "$DROPIN_FILE" ]] && cmp -s <(printf '%s' "$NEW_DROPIN") "$DROPIN_FILE"; then
    log "drop-in unchanged at $DROPIN_FILE"
  elif [[ "$APPLY_MODE" == "apply" ]]; then
    printf '%s' "$NEW_DROPIN" >"$DROPIN_FILE"
    log "wrote $DROPIN_FILE"
    systemctl --user daemon-reload
    systemctl --user restart ollama.service
    log "restarted ollama.service"
  else
    log "observe: would write drop-in to $DROPIN_FILE:"
    printf '%s\n' "$NEW_DROPIN"
  fi
fi

while IFS= read -r model; do
  [[ -z "$model" ]] && continue
  if [[ "$APPLY_MODE" == "apply" ]]; then
    log "pulling missing model: $model"
    ollama pull "$model" || {
      echo "apply-runner-host: ollama pull failed for $model" >&2
      exit 1
    }
  else
    log "observe: would pull missing model: $model"
  fi
done < <(missing_models)

log "done"
