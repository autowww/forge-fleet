#!/usr/bin/env bash
# install-caddy-fleet-ollama-unified.sh — one HTTP port for Forge Fleet + Ollama via Caddy.
#
# Stops the existing forge-fleet-caddy service (user or system), backs up the prior
# Caddyfile, writes a merged config, validates, and starts Caddy again.
#
# Routing (same listener):
#   Fleet (first): /v1/health, /v1/version — always to forge-fleet (avoids misconfigs that send all /v1/* to Ollama).
#   Ollama:        /v1/chat/completions*, /v1/completions*, /v1/models*, /v1/embeddings*, /api/*
#   Fleet (catch): all other routes (/v1/jobs, /admin/, …)
#
# Prerequisites: caddy on PATH; Fleet and Ollama listening on their loopback ports.
#
# Usage:
#   ./scripts/install-caddy-fleet-ollama-unified.sh
#   LAYOUT=user FLEET_BEARER_TOKEN='f' LLM_BEARER_TOKEN='l' ./scripts/install-caddy-fleet-ollama-unified.sh --non-interactive
#   LAYOUT=system FLEET_BEARER_TOKEN='secret' sudo -E ./scripts/install-caddy-fleet-ollama-unified.sh --non-interactive
#
# Env (optional):
#   FLEET_UPSTREAM_HOST (default 127.0.0.1)
#   FLEET_UPSTREAM_PORT (default 18766 user / 18765 system)
#   OLLAMA_UPSTREAM_HOST (default 127.0.0.1)
#   OLLAMA_UPSTREAM_PORT (default 11434)
#   CADDY_PUBLIC_PORT    (default 18767 user / 18766 system)
#   FLEET_BEARER_TOKEN   — injected upstream to Fleet (clients need not send it)
#   LLM_BEARER_TOKEN     — optional; when set, clients must send this Bearer on Ollama routes;
#                          differs from Fleet token; stripped before proxy to Ollama
#   CADDY_SITE_ADDRESS   — optional site block label instead of :PORT (e.g. granite.forgedc.net
#                          or granite.forgedc.net:8443 for TLS / alternate port; empty = :CADDY_PUBLIC_PORT)
#   STOP_DISTRO_CADDY=1  — stop stock caddy.service if active (frees :80 etc.; does not disable)
#   SKIP_BACKUP=1        — do not write .bak before overwrite
#
# See also: docs/CADDY-SYSTEMD.md, scripts/install-caddy-fleet.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

INTERACTIVE=1
LAYOUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --non-interactive|-n) INTERACTIVE=0; shift ;;
    --layout)
      LAYOUT="${2:-}"
      shift 2
      ;;
    -h|--help)
      sed -n '3,34p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown option: $1 (try --help)" >&2
      exit 2
      ;;
  esac
done

die() { echo "install-caddy-fleet-ollama-unified: $*" >&2; exit 1; }

log() { printf '%s\n' "$*"; }

# GNU bash: editable default on TTY; plain prompt fallback otherwise.
read_default() {
  local __out="$1" __cur="$2" __def="$3" __prompt="$4"
  local __iv="${__cur:-$__def}"
  local __v=""
  if [[ -t 0 ]]; then
    read -e -i "$__iv" -p "$__prompt" __v || true
  else
    read -r -p "$__prompt [${__iv}]: " __v || true
  fi
  if [[ -z "${__v:-}" ]]; then
    printf -v "$__out" '%s' "$__iv"
  else
    printf -v "$__out" '%s' "$__v"
  fi
}

escape_caddy_dq() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

_emit_fleet_upstream() {
  # stdout: indented reverse_proxy stanza (tabs); args: fleet_host fleet_port esc_f fleet_bearer
  local fh="$1" fp="$2" esc="$3" fb="$4"
  if [[ -n "${fb// }" ]]; then
    printf '		reverse_proxy %s:%s {\n' "$fh" "$fp"
    printf '			header_up Authorization "Bearer %s"\n' "$esc"
    printf '		}\n'
  else
    printf '		reverse_proxy %s:%s\n' "$fh" "$fp"
  fi
}

write_unified_caddyfile() {
  local out="$1" public_port="$2" fleet_host="$3" fleet_port="$4" ollama_host="$5" ollama_port="$6" fleet_bearer="$7" llm_bearer="$8" site_address="${9:-}"
  local esc_f esc_l
  esc_f="$(escape_caddy_dq "$fleet_bearer")"
  esc_l="$(escape_caddy_dq "$llm_bearer")"
  {
    printf '%s\n' '{' '	admin off' '}' ''
    if [[ -n "${site_address// }" ]]; then
      printf '%s {\n' "${site_address}"
    else
      printf ':%s {\n' "${public_port}"
    fi
    printf '	encode gzip\n'
    printf '\n'
    printf '	# Forge Fleet — health/version before Ollama (single-host granite-style split)\n'
    printf '	@fleet_health {\n'
    printf '		path /v1/health /v1/version\n'
    printf '	}\n'
    printf '	handle @fleet_health {\n'
    _emit_fleet_upstream "$fleet_host" "$fleet_port" "$esc_f" "$fleet_bearer"
    printf '	}\n'
    printf '\n'
    printf '	# Ollama — OpenAI /v1 + /api (optional LLM bearer checked at this edge)\n'
    printf '	@ollama {\n'
    printf '		path /v1/chat/completions*\n'
    printf '		path /v1/completions*\n'
    printf '		path /v1/models*\n'
    printf '		path /v1/embeddings*\n'
    printf '		path /api/*\n'
    printf '	}\n'
    printf '	handle @ollama {\n'
    if [[ -n "${llm_bearer// }" ]]; then
      printf '		@deny_llm not header Authorization "Bearer %s"\n' "${esc_l}"
      printf '		respond @deny_llm "Unauthorized" 401\n'
      printf '		reverse_proxy %s:%s {\n' "$ollama_host" "$ollama_port"
      printf '			header_up -Authorization\n'
      printf '		}\n'
    else
      printf '		reverse_proxy %s:%s\n' "$ollama_host" "$ollama_port"
    fi
    printf '	}\n'
    printf '\n'
    printf '	# Forge Fleet — remaining routes (/v1/jobs, /admin/, …)\n'
    printf '	handle {\n'
    _emit_fleet_upstream "$fleet_host" "$fleet_port" "$esc_f" "$fleet_bearer"
    printf '	}\n'
    printf '}\n'
  } >"$out"
}

backup_file() {
  local f="$1"
  [[ -f "$f" ]] || return 0
  [[ "${SKIP_BACKUP:-0}" == "1" ]] && return 0
  local ts
  ts="$(date +%Y%m%d%H%M%S)"
  cp -a "$f" "${f}.bak.${ts}"
  log "Backed up: $f -> ${f}.bak.${ts}"
}

stop_fleet_caddy_user() {
  if systemctl --user cat forge-fleet-caddy.service &>/dev/null; then
    systemctl --user stop forge-fleet-caddy.service 2>/dev/null || true
    log "Stopped: systemctl --user stop forge-fleet-caddy.service"
  else
    log "(no user forge-fleet-caddy.service — will create if needed)"
  fi
}

stop_fleet_caddy_system() {
  if [[ -f /etc/systemd/system/forge-fleet-caddy.service ]]; then
    systemctl stop forge-fleet-caddy.service 2>/dev/null || true
    log "Stopped: systemctl stop forge-fleet-caddy.service"
  else
    log "(no /etc/systemd/system/forge-fleet-caddy.service — will create if needed)"
  fi
}

maybe_stop_distro_caddy() {
  [[ "${STOP_DISTRO_CADDY:-0}" == "1" ]] || return 0
  if command -v systemctl >/dev/null && systemctl cat caddy.service &>/dev/null; then
    if systemctl is-active --quiet caddy.service 2>/dev/null; then
      systemctl stop caddy.service && log "Stopped stock caddy.service (STOP_DISTRO_CADDY=1)."
    else
      log "Stock caddy.service not active; nothing to stop."
    fi
  fi
}

write_user_unit_if_needed() {
  local public_port="$1"
  local unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  local unit_file="$unit_dir/forge-fleet-caddy.service"
  mkdir -p "$unit_dir"
  cat >"$unit_file" <<EOF
[Unit]
Description=Caddy — Forge Fleet + Ollama reverse proxy (user, HTTP :${public_port})
After=network-online.target forge-fleet.service
Wants=forge-fleet.service

[Service]
Type=simple
ExecStart=/usr/bin/caddy run --config %h/.config/forge-fleet/Caddyfile.caddy-fleet
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF
}

run_user_systemd() {
  systemctl --user daemon-reload
  systemctl --user enable forge-fleet-caddy.service
  systemctl --user restart forge-fleet-caddy.service
  log ""
  log "Started: systemctl --user status forge-fleet-caddy.service"
  systemctl --user --no-pager --full status forge-fleet-caddy.service || true
}

run_system_systemd() {
  local unit_src="$REPO_ROOT/systemd/forge-fleet-caddy.service"
  [[ -f "$unit_src" ]] || die "missing $unit_src"
  install -m0644 "$unit_src" /etc/systemd/system/forge-fleet-caddy.service
  systemctl daemon-reload
  systemctl enable forge-fleet-caddy.service
  systemctl restart forge-fleet-caddy.service
  log ""
  log "Started: systemctl status forge-fleet-caddy.service"
  systemctl --no-pager --full status forge-fleet-caddy.service || true
}

upsert_env_line() {
  local key="$1" val="$2" file="$3"
  mkdir -p "$(dirname "$file")"
  touch "$file"
  if grep -qE "^[[:space:]]*${key}=" "$file" 2>/dev/null; then
    sed -i "/^[[:space:]]*${key}=/d" "$file"
  fi
  printf '%s=%s\n' "$key" "$val" >>"$file"
}

read_bearer() {
  local env_file="${1:-}"
  local hint=""
  [[ -n "${FLEET_BEARER_TOKEN// }" ]] && hint="${hint:+$hint; }env has FLEET_BEARER_TOKEN"
  if [[ -n "$env_file" && -f "$env_file" ]] && grep -qE '^[[:space:]]*FLEET_BEARER_TOKEN=[^[:space:]]+' "$env_file" 2>/dev/null; then
    hint="${hint:+$hint; }$env_file saves a token"
  fi
  log ""
  log "FLEET_BEARER_TOKEN — Caddy injects this to the Fleet upstream (leave empty for no injection)."
  [[ -n "$hint" ]] && log "  ($hint — leave input empty to keep env/file value)"
  log "  Enter new token, or press Enter to keep:"
  read -rs token || true
  log ""
  if [[ -n "${token// }" ]]; then
    FLEET_BEARER_TOKEN="$token"
  elif [[ -n "${FLEET_BEARER_TOKEN:-}" ]]; then
    :
  elif [[ -n "$env_file" && -f "$env_file" ]]; then
    FLEET_BEARER_TOKEN="$(grep -E '^[[:space:]]*FLEET_BEARER_TOKEN=' "$env_file" | head -1 | sed 's/^[^=]*=//')"
  fi
}

read_llm_bearer() {
  local env_file="${1:-}"
  local hint=""
  [[ -n "${LLM_BEARER_TOKEN// }" ]] && hint="${hint:+$hint; }env has LLM_BEARER_TOKEN"
  if [[ -n "$env_file" && -f "$env_file" ]] && grep -qE '^[[:space:]]*LLM_BEARER_TOKEN=[^[:space:]]+' "$env_file" 2>/dev/null; then
    hint="${hint:+$hint; }$env_file saves a token"
  fi
  log ""
  log "LLM_BEARER_TOKEN — optional; when set, clients must send this Bearer on Ollama routes (empty = no gate)."
  [[ -n "$hint" ]] && log "  ($hint — leave input empty to keep env/file value)"
  log "  Enter new token, or press Enter to keep:"
  read -rs ltok || true
  log ""
  if [[ -n "${ltok// }" ]]; then
    LLM_BEARER_TOKEN="$ltok"
  elif [[ -n "${LLM_BEARER_TOKEN:-}" ]]; then
    :
  elif [[ -n "$env_file" && -f "$env_file" ]]; then
    LLM_BEARER_TOKEN="$(grep -E '^[[:space:]]*LLM_BEARER_TOKEN=' "$env_file" | head -1 | sed 's/^[^=]*=//')"
  fi
}

prompt_layout() {
  log ""
  log "=== Unified Caddy (Fleet + Ollama) ==="
  log "1) User Fleet   — systemd --user (typical: Fleet :18766, Caddy :18767)"
  log "2) System Fleet — /opt layout (Fleet :18765, Caddy :18766)"
  read -rp "Choose [1]: " n
  case "${n:-1}" in
    2) LAYOUT=system ;;
    *) LAYOUT=user ;;
  esac
}

prompt_ports_user() {
  log ""
  log "--- Ports (editable defaults; Enter accepts current line) ---"
  read_default FLEET_UPSTREAM_HOST "$FLEET_UPSTREAM_HOST" "127.0.0.1" "Fleet upstream host: "
  read_default FLEET_UPSTREAM_PORT "$FLEET_UPSTREAM_PORT" "18766" "Fleet upstream port: "
  read_default OLLAMA_UPSTREAM_HOST "$OLLAMA_UPSTREAM_HOST" "127.0.0.1" "Ollama upstream host: "
  read_default OLLAMA_UPSTREAM_PORT "$OLLAMA_UPSTREAM_PORT" "11434" "Ollama upstream port: "
  read_default CADDY_PUBLIC_PORT "$CADDY_PUBLIC_PORT" "18767" "Caddy public HTTP port: "
  if [[ "$CADDY_PUBLIC_PORT" == "$FLEET_UPSTREAM_PORT" ]]; then
    die "Caddy public port must differ from Fleet upstream port"
  fi
}

prompt_ports_system() {
  log ""
  log "--- Ports (editable defaults; Enter accepts current line) ---"
  read_default FLEET_UPSTREAM_HOST "$FLEET_UPSTREAM_HOST" "127.0.0.1" "Fleet upstream host: "
  read_default FLEET_UPSTREAM_PORT "$FLEET_UPSTREAM_PORT" "18765" "Fleet upstream port: "
  read_default OLLAMA_UPSTREAM_HOST "$OLLAMA_UPSTREAM_HOST" "127.0.0.1" "Ollama upstream host: "
  read_default OLLAMA_UPSTREAM_PORT "$OLLAMA_UPSTREAM_PORT" "11434" "Ollama upstream port: "
  read_default CADDY_PUBLIC_PORT "$CADDY_PUBLIC_PORT" "18766" "Caddy public HTTP port: "
  if [[ "$CADDY_PUBLIC_PORT" == "$FLEET_UPSTREAM_PORT" ]]; then
    die "Caddy public port must differ from Fleet upstream port"
  fi
}

ensure_caddy_bin() {
  command -v caddy >/dev/null || die "caddy not on PATH (e.g. apt install caddy)"
}

# --- defaults ---
FLEET_UPSTREAM_HOST="${FLEET_UPSTREAM_HOST:-127.0.0.1}"
OLLAMA_UPSTREAM_HOST="${OLLAMA_UPSTREAM_HOST:-127.0.0.1}"
OLLAMA_UPSTREAM_PORT="${OLLAMA_UPSTREAM_PORT:-11434}"
FLEET_UPSTREAM_PORT="${FLEET_UPSTREAM_PORT:-}"
CADDY_PUBLIC_PORT="${CADDY_PUBLIC_PORT:-}"
FLEET_BEARER_TOKEN="${FLEET_BEARER_TOKEN:-}"
LLM_BEARER_TOKEN="${LLM_BEARER_TOKEN:-}"
CADDY_SITE_ADDRESS="${CADDY_SITE_ADDRESS:-}"

if [[ "$INTERACTIVE" -eq 1 ]]; then
  [[ -n "$LAYOUT" ]] || prompt_layout
else
  [[ -n "${LAYOUT:-}" ]] || die "Set LAYOUT=user or LAYOUT=system for --non-interactive"
fi

LAYOUT="${LAYOUT:?}"

case "$LAYOUT" in
  user)
    CFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/forge-fleet"
    ENV_FILE="$CFG_DIR/forge-fleet.env"
    CADDYFILE="$CFG_DIR/Caddyfile.caddy-fleet"
    FLEET_UPSTREAM_PORT="${FLEET_UPSTREAM_PORT:-18766}"
    CADDY_PUBLIC_PORT="${CADDY_PUBLIC_PORT:-18767}"

    if [[ "$INTERACTIVE" -eq 1 ]]; then
      mkdir -p "$CFG_DIR"
      prompt_ports_user
      log ""
      log "--- Bearers (hidden input) ---"
      read_bearer "$ENV_FILE"
      [[ -n "${FLEET_BEARER_TOKEN:-}" ]] && upsert_env_line FLEET_BEARER_TOKEN "$FLEET_BEARER_TOKEN" "$ENV_FILE"
      read_llm_bearer "$ENV_FILE"
      [[ -n "${LLM_BEARER_TOKEN:-}" ]] && upsert_env_line LLM_BEARER_TOKEN "$LLM_BEARER_TOKEN" "$ENV_FILE"
    fi

    [[ "$CADDY_PUBLIC_PORT" != "$FLEET_UPSTREAM_PORT" ]] || die "Caddy port must differ from Fleet upstream port"

    stop_fleet_caddy_user
    maybe_stop_distro_caddy

    ensure_caddy_bin
    mkdir -p "$CFG_DIR"
    backup_file "$CADDYFILE"
    write_unified_caddyfile "$CADDYFILE" "$CADDY_PUBLIC_PORT" "$FLEET_UPSTREAM_HOST" "$FLEET_UPSTREAM_PORT" \
      "$OLLAMA_UPSTREAM_HOST" "$OLLAMA_UPSTREAM_PORT" "$FLEET_BEARER_TOKEN" "$LLM_BEARER_TOKEN" "${CADDY_SITE_ADDRESS:-}"
    chmod 0600 "$CADDYFILE"

    if ! caddy validate --config "$CADDYFILE" 2>&1; then
      die "caddy validate failed — fix $CADDYFILE; logs: journalctl --user -xeu forge-fleet-caddy.service"
    fi

    write_user_unit_if_needed "$CADDY_PUBLIC_PORT"
    run_user_systemd

    log ""
    if [[ -n "${CADDY_SITE_ADDRESS// }" ]]; then
      log "Unified site block: ${CADDY_SITE_ADDRESS} (see Caddyfile; TLS uses automatic HTTPS when hostname has no :port suffix)"
    else
      log "Unified listener: http://0.0.0.0:${CADDY_PUBLIC_PORT}/"
    fi
    log "  → Ollama  ${OLLAMA_UPSTREAM_HOST}:${OLLAMA_UPSTREAM_PORT}  (paths: /v1/chat/completions, /v1/models, /api/*, …)"
    log "             LLM edge bearer: $( [[ -n "${LLM_BEARER_TOKEN// }" ]] && echo required || echo off )"
    log "  → Fleet   ${FLEET_UPSTREAM_HOST}:${FLEET_UPSTREAM_PORT}  (inject bearer: $( [[ -n "${FLEET_BEARER_TOKEN// }" ]] && echo yes || echo no ))"
    log "Boot without login: loginctl enable-linger $USER"
    ;;

  system)
    [[ "$(id -u)" -eq 0 ]] || die "System layout requires root: sudo -E $0 $*"
    CADDYFILE="/etc/forge-fleet/Caddyfile"
    FLEET_UPSTREAM_PORT="${FLEET_UPSTREAM_PORT:-18765}"
    CADDY_PUBLIC_PORT="${CADDY_PUBLIC_PORT:-18766}"

    if [[ "$INTERACTIVE" -eq 1 ]]; then
      install -d -m0755 /etc/forge-fleet
      touch /etc/forge-fleet/caddy.env
      chmod 0600 /etc/forge-fleet/caddy.env 2>/dev/null || true
      prompt_ports_system
      log ""
      log "--- Bearers (hidden input) ---"
      read_bearer "/etc/forge-fleet/caddy.env"
      [[ -n "${FLEET_BEARER_TOKEN:-}" ]] && upsert_env_line FLEET_BEARER_TOKEN "$FLEET_BEARER_TOKEN" "/etc/forge-fleet/caddy.env"
      read_llm_bearer "/etc/forge-fleet/caddy.env"
      [[ -n "${LLM_BEARER_TOKEN:-}" ]] && upsert_env_line LLM_BEARER_TOKEN "$LLM_BEARER_TOKEN" "/etc/forge-fleet/caddy.env"
    else
      : # tokens may come only from env / Caddyfile when non-interactive
    fi

    [[ "$CADDY_PUBLIC_PORT" != "$FLEET_UPSTREAM_PORT" ]] || die "Caddy port must differ from Fleet upstream port"

    stop_fleet_caddy_system
    maybe_stop_distro_caddy

    ensure_caddy_bin
    install -d -m0755 /etc/forge-fleet
    backup_file "$CADDYFILE"
    write_unified_caddyfile "$CADDYFILE" "$CADDY_PUBLIC_PORT" "$FLEET_UPSTREAM_HOST" "$FLEET_UPSTREAM_PORT" \
      "$OLLAMA_UPSTREAM_HOST" "$OLLAMA_UPSTREAM_PORT" "$FLEET_BEARER_TOKEN" "$LLM_BEARER_TOKEN" "${CADDY_SITE_ADDRESS:-}"
    if id -u caddy &>/dev/null; then
      chown root:caddy "$CADDYFILE"
      chmod 0640 "$CADDYFILE"
    else
      chmod 0600 "$CADDYFILE"
    fi

    caddy validate --config "$CADDYFILE" || die "caddy validate failed — check $CADDYFILE"
    run_system_systemd

    log ""
    if [[ -n "${CADDY_SITE_ADDRESS// }" ]]; then
      log "Unified site block: ${CADDY_SITE_ADDRESS}"
    else
      log "Unified listener: http://0.0.0.0:${CADDY_PUBLIC_PORT}/"
    fi
    log "  → Ollama  ${OLLAMA_UPSTREAM_HOST}:${OLLAMA_UPSTREAM_PORT}  (LLM edge bearer: $( [[ -n "${LLM_BEARER_TOKEN// }" ]] && echo required || echo off ))"
    log "  → Fleet   ${FLEET_UPSTREAM_HOST}:${FLEET_UPSTREAM_PORT}  (inject bearer: $( [[ -n "${FLEET_BEARER_TOKEN// }" ]] && echo yes || echo no ))"
    ;;

  *) die "LAYOUT must be user or system (got $LAYOUT)" ;;
esac
