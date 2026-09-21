"""Operator UI settings and setup recipe generation (stdlib only)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_DEFAULTS: dict[str, Any] = {
    "machine_role": "laptop",
    "connection": {
        "peer_id": "remote",
        "peer_label": "Remote Fleet",
        "remote_base_url": "",
    },
    "edge": {
        "public_hostname": "",
        "caddy_port": 18767,
        "layout": "system",
        "forge_fleet_checkout": "/opt/forge-fleet",
    },
}


def settings_file(data_dir: Path) -> Path:
    return data_dir / "etc" / "operator-ui-settings.json"


def _load_raw(data_dir: Path) -> dict[str, Any]:
    path = settings_file(data_dir)
    if not path.is_file():
        return json.loads(json.dumps(_DEFAULTS))
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return json.loads(json.dumps(_DEFAULTS))
    if not isinstance(doc, dict):
        return json.loads(json.dumps(_DEFAULTS))
    return doc


def _merge_defaults(doc: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(_DEFAULTS))
    role = str(doc.get("machine_role") or out["machine_role"]).strip().lower()
    if role in ("laptop", "server"):
        out["machine_role"] = role
    conn = doc.get("connection") if isinstance(doc.get("connection"), dict) else {}
    for key in ("peer_id", "peer_label", "remote_base_url"):
        if key in conn:
            out["connection"][key] = str(conn.get(key) or "").strip()
    edge = doc.get("edge") if isinstance(doc.get("edge"), dict) else {}
    if "public_hostname" in edge:
        out["edge"]["public_hostname"] = str(edge.get("public_hostname") or "").strip()
    if "forge_fleet_checkout" in edge:
        out["edge"]["forge_fleet_checkout"] = str(edge.get("forge_fleet_checkout") or "").strip() or out["edge"]["forge_fleet_checkout"]
    layout = str(edge.get("layout") or out["edge"]["layout"]).strip().lower()
    if layout in ("user", "system"):
        out["edge"]["layout"] = layout
    try:
        port = int(edge.get("caddy_port", out["edge"]["caddy_port"]))
        if 1 <= port <= 65535:
            out["edge"]["caddy_port"] = port
    except (TypeError, ValueError):
        pass
    out["updated_at"] = doc.get("updated_at")
    return out


def get_settings(data_dir: Path) -> dict[str, Any]:
    doc = _merge_defaults(_load_raw(data_dir))
    return {"ok": True, "settings": doc, "recipes": build_recipes(doc)}


def put_settings(data_dir: Path, body: dict[str, Any]) -> dict[str, Any]:
    current = _merge_defaults(_load_raw(data_dir))
    if "machine_role" in body:
        role = str(body.get("machine_role") or "").strip().lower()
        if role in ("laptop", "server"):
            current["machine_role"] = role
    if isinstance(body.get("connection"), dict):
        conn = body["connection"]
        for key in ("peer_id", "peer_label", "remote_base_url"):
            if key in conn:
                current["connection"][key] = str(conn.get(key) or "").strip()
    if isinstance(body.get("edge"), dict):
        edge = body["edge"]
        if "public_hostname" in edge:
            current["edge"]["public_hostname"] = str(edge.get("public_hostname") or "").strip()
        if "forge_fleet_checkout" in edge:
            val = str(edge.get("forge_fleet_checkout") or "").strip()
            if val:
                current["edge"]["forge_fleet_checkout"] = val
        layout = str(edge.get("layout") or "").strip().lower()
        if layout in ("user", "system"):
            current["edge"]["layout"] = layout
        if "caddy_port" in edge:
            try:
                port = int(edge.get("caddy_port"))
                if 1 <= port <= 65535:
                    current["edge"]["caddy_port"] = port
            except (TypeError, ValueError):
                pass
    current["updated_at"] = time.time()
    path = settings_file(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return {"ok": True, "settings": current, "recipes": build_recipes(current)}


def _public_base(url: str, hostname: str) -> str:
    u = (url or "").strip().rstrip("/")
    if u:
        return u
    h = (hostname or "").strip()
    if not h:
        return "https://<FLEET_PUBLIC_HOSTNAME>"
    if h.startswith("http://") or h.startswith("https://"):
        return h.rstrip("/")
    return f"https://{h}"


def build_recipes(settings: dict[str, Any]) -> list[dict[str, Any]]:
    conn = settings.get("connection") or {}
    edge = settings.get("edge") or {}
    role = str(settings.get("machine_role") or "laptop")
    peer_id = str(conn.get("peer_id") or "remote")
    base = _public_base(str(conn.get("remote_base_url") or ""), str(edge.get("public_hostname") or ""))
    host = str(edge.get("public_hostname") or "<FLEET_PUBLIC_HOSTNAME>").strip()
    if host.startswith("http://") or host.startswith("https://"):
        try:
            from urllib.parse import urlparse

            host = urlparse(host).hostname or host
        except Exception:
            pass
    port = int(edge.get("caddy_port") or 18767)
    checkout = str(edge.get("forge_fleet_checkout") or "/opt/forge-fleet")
    layout = str(edge.get("layout") or "system")

    recipes: list[dict[str, Any]] = [
        {
            "id": "ui_connection",
            "title": "Connection (Fleet web UI — no shell)",
            "runs_as": "ui",
            "summary": "Save settings and remote peer credentials through this admin panel.",
            "steps": [
                {
                    "label": "Save settings",
                    "detail": "Stores peer id, label, and URLs in operator-ui-settings.json (no bearer).",
                },
                {
                    "label": "Save connection",
                    "detail": "Also writes bearer to remote-peers.json when token is provided.",
                },
                {
                    "label": "Probe remote health",
                    "detail": "POST /v1/remote-peers/{id}/probe via local Fleet proxy.",
                },
            ],
        },
        {
            "id": "user_laptop",
            "title": "Laptop cockpit (run as your user — no root)",
            "runs_as": "user",
            "only_when": {"machine_role": "laptop"},
            "steps": [
                {
                    "label": "Enable user Fleet unit",
                    "commands": ["land-fleet setup-user", "loginctl enable-linger \"$USER\""],
                },
                {
                    "label": "Verify local health",
                    "commands": ["curl -fsS http://127.0.0.1:18766/v1/health"],
                },
                {
                    "label": "Register remote peer (optional CLI)",
                    "commands": [
                        "export FORGE_FLEET_BASE_URL='" + base + "'",
                        "export FORGE_FLEET_BEARER_TOKEN='<FLEET_BEARER_TOKEN>'",
                        "land-fleet join --coordinator \"${FORGE_FLEET_BASE_URL}\" "
                        f"--enroll-token \"${{FORGE_FLEET_BEARER_TOKEN}}\" --label {peer_id}",
                    ],
                },
            ],
        },
    ]

    if role == "server":
        recipes.append(
            {
                "id": "root_cloudflared",
                "title": "Cloudflare tunnel (run as root on this server)",
                "runs_as": "root",
                "only_when": {"machine_role": "server"},
                "summary": "Install cloudflared and attach tunnel token from Cloudflare Zero Trust.",
                "steps": [
                    {
                        "label": "Install cloudflared package",
                        "commands": [
                            "curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg "
                            "| tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null",
                            'echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] '
                            "https://pkg.cloudflare.com/cloudflared "
                            '$(. /etc/os-release && echo $VERSION_CODENAME) main" '
                            "| tee /etc/apt/sources.list.d/cloudflared.list",
                            "apt-get update && apt-get install -y cloudflared",
                        ],
                    },
                    {
                        "label": "Install tunnel service",
                        "commands": [
                            "cloudflared service install <CLOUDFLARE_TUNNEL_TOKEN>",
                            "systemctl enable --now cloudflared",
                        ],
                    },
                    {
                        "label": "Cloudflare dashboard",
                        "detail": (
                            f"Public Hostname → http://127.0.0.1:{port} "
                            f"(unified Caddy must listen on this port)."
                        ),
                    },
                ],
            }
        )
        recipes.append(
            {
                "id": "root_or_user_caddy",
                "title": "Unified Caddy edge (after tunnel)",
                "runs_as": "root" if layout == "system" else "user",
                "only_when": {"machine_role": "server"},
                "summary": "Routes /v1/health to Fleet before Ollama. Match layout to your install.",
                "steps": [
                    {
                        "label": "Run unified installer",
                        "commands": [
                            f"cd {checkout}",
                            f"CADDY_SITE_ADDRESS={host} \\",
                            f"LAYOUT={layout} \\",
                            "FLEET_BEARER_TOKEN='<FLEET_BEARER_TOKEN>' \\",
                            "LLM_BEARER_TOKEN='<LLM_BEARER_TOKEN>' \\",
                            "bash ./scripts/install-caddy-fleet-ollama-unified.sh --non-interactive",
                        ],
                    },
                    {
                        "label": "Restart Caddy",
                        "commands": [
                            "systemctl restart forge-fleet-caddy.service"
                            if layout == "system"
                            else "systemctl --user restart forge-fleet-caddy.service"
                        ],
                    },
                    {
                        "label": "Verify public Fleet health",
                        "commands": [
                            f"curl -fsS -H 'Authorization: Bearer <FLEET_BEARER_TOKEN>' {base}/v1/health",
                        ],
                    },
                ],
            }
        )

    return recipes
