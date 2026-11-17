#!/usr/bin/env bash
# Point Open WebUI OAuth at the same Google Web client as Lenses (Mercury / production).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY="$(cd "$SCRIPT_DIR/.." && pwd)"
WEBUI_ENV="${1:-$DEPLOY/.env}"
OIDC_ENV="${LENSES_GATEWAY_OIDC_ENV:-${HOME}/.local/share/forge-lenses-gateway/oidc.env}"

if [[ ! -f "$WEBUI_ENV" ]]; then
  echo "Missing $WEBUI_ENV — copy .env.example first." >&2
  exit 1
fi
if [[ ! -f "$OIDC_ENV" ]]; then
  echo "Missing Google OIDC env at $OIDC_ENV" >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a && source "$OIDC_ENV" && set +a

CLIENT_ID="${LENSES_OIDC_CLIENT_ID:-}"
CLIENT_SECRET="${LENSES_OIDC_CLIENT_SECRET:-}"
WEBUI_BASE="${WEBUI_URL:-https://webui.forgedc.net}"
WEBUI_BASE="${WEBUI_BASE%/}"

if [[ -z "$CLIENT_ID" || -z "$CLIENT_SECRET" ]]; then
  echo "LENSES_OIDC_CLIENT_ID and LENSES_OIDC_CLIENT_SECRET must be set in $OIDC_ENV" >&2
  exit 1
fi

python3 <<PY
from pathlib import Path
import re

WEBUI_BASE = """$WEBUI_BASE"""
path = Path("$WEBUI_ENV")
text = path.read_text(encoding="utf-8") if path.is_file() else ""
lines = [ln for ln in text.splitlines() if ln.strip()]

def upsert(key: str, val: str) -> None:
    global lines
    pat = re.compile(rf"^{re.escape(key)}=")
    lines = [ln for ln in lines if not pat.match(ln)]
    lines.append(f"{key}={val}")

upsert("ENABLE_OAUTH", "true")
upsert("OAUTH_PROVIDER_NAME", "google")
upsert("OAUTH_CLIENT_ID", "$CLIENT_ID")
upsert("OAUTH_CLIENT_SECRET", "$CLIENT_SECRET")
upsert("OPENID_PROVIDER_URL", "https://accounts.google.com")
upsert("OPENID_REDIRECT_URI", f"$WEBUI_BASE/oauth/google/callback")
upsert("ENABLE_OAUTH_SIGNUP", "false")
upsert("ENABLE_SIGNUP", "false")
upsert("ENABLE_LOGIN_FORM", "false")

path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Updated {path} for Google sign-in")
print("Add this redirect URI in Google Cloud:", f"{WEBUI_BASE}/oauth/google/callback")
PY