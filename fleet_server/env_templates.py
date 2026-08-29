"""Environment templates: descriptors and .env rendering for compose-based apps."""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

_ENV_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def _slug_suffix(env_id: str) -> str:
    e = str(env_id or "").strip().lower()
    if e in ("prod", "production"):
        return ""
    if e == "dev":
        return "-dev"
    return f"-{e}"


def _compose_project(app_id: str, env_id: str) -> str:
    base = str(app_id or "").strip()
    suf = _slug_suffix(env_id)
    if suf and base.endswith(suf):
        return base
    return f"{base}{suf}"


def _volume_suffix(env_id: str) -> str:
    e = str(env_id or "").strip().lower()
    if e in ("prod", "production"):
        return ""
    return f"_{e}"


# Built-in templates keyed by template_id
_TEMPLATES: dict[str, dict[str, Any]] = {
    "forge_market_studio": {
        "id": "forge_market_studio",
        "app_id": "forge-market-studio",
        "type_id": "forge_market_studio",
        "title": "Forge Market Studio",
        "source_compose_root": "deploy/forge-market-studio",
        "compose_overlay": "compose.granite.yaml",
        "app_service_name": "market-app",
        "postgres_service_name": "postgres",
        "migrate_command": ["run", "--rm", "--no-deps", "market-app", "python", "-m", "forge_market.db.migrate", "upgrade"],
        "port_ranges": {
            "app": (19790, 19810),
            "postgres": (15430, 15450),
        },
        "default_ports": {
            "prod": {"app": 19792, "postgres": 15432},
            "dev": {"app": 19793, "postgres": 15433},
            "clean": {"app": 19794, "postgres": 15434},
        },
        "gateway": {
            "slug_pattern": "market-studio{suffix}",
            "upstream_port_key": "app",
            "bearer_env": "FORGE_MARKET_STUDIO_API_TOKEN",
        },
        "container_service": {
            "id_pattern": "market-studio{suffix}",
            "label_pattern": "Granite Market Studio{label_suffix}",
        },
        "env_rewrites": [
            {"key": "FORGE_MARKET_COMPOSE_PROJECT", "kind": "compose_project"},
            {"key": "FORGE_MARKET_PG_CONTAINER", "kind": "container_name", "base": "forge-market-postgres"},
            {"key": "FORGE_MARKET_APP_CONTAINER", "kind": "container_name", "base": "forge-market-app"},
            {"key": "FORGE_MARKET_APP_IMAGE", "kind": "literal", "value": "forge-market-app:studio"},
            {"key": "FORGE_MARKET_PGDATA_VOLUME", "kind": "volume", "base": "forge_market_studio_pgdata"},
            {"key": "FORGE_MARKET_APPDATA_VOLUME", "kind": "volume", "base": "forge_market_studio_data"},
            {"key": "FORGE_MARKET_STUDIO_HOST_PORT", "kind": "port", "port_key": "app"},
            {"key": "FORGE_MARKET_POSTGRES_HOST_PORT", "kind": "port", "port_key": "postgres"},
        ],
        "prod_only_keys": [
            "IBKR_FLEX_TOKEN",
            "IBKR_FLEX_NAV_QUERY_ID",
            "IBKR_FLEX_TRADES_QUERY_ID",
            "IBKR_FLEX_POSITIONS_QUERY_ID",
            "IBKR_FLEX_CASH_QUERY_ID",
        ],
        "dev_extra_keys": [
            {"key": "FORGE_MARKET_GIT_SHA", "kind": "literal", "value": ""},
            {"key": "POSTGRES_PASSWORD", "kind": "literal", "value": "forge_market_dev"},
            {
                "key": "FORGE_MARKET_DATABASE_URL",
                "kind": "literal",
                "value": "postgresql://forge_market:forge_market_dev@postgres:5432/forge_market",
            },
        ],
    },
}


def list_templates(*, app_id: str | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tpl in _TEMPLATES.values():
        if app_id and tpl.get("app_id") != app_id:
            continue
        out.append(public_template(tpl))
    return out


def get_template(template_id: str) -> dict[str, Any] | None:
    return _TEMPLATES.get(str(template_id or "").strip())


def public_template(tpl: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": tpl["id"],
        "app_id": tpl["app_id"],
        "type_id": tpl["type_id"],
        "title": tpl.get("title", tpl["id"]),
        "compose_overlay": tpl.get("compose_overlay"),
        "port_ranges": tpl.get("port_ranges"),
        "default_ports": tpl.get("default_ports"),
    }


def _read_env_lines(path: Path) -> list[tuple[str, str]]:
    if not path.is_file():
        return []
    lines: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _ENV_LINE_RE.match(raw.strip())
        if m:
            val = m.group(2)
            if " #" in val:
                val = val.split(" #", 1)[0].rstrip()
            lines.append((m.group(1), val))
    return lines


def _volume_name(base: str, env_id: str) -> str:
    suf = _volume_suffix(env_id)
    if not suf:
        return base
    for ending in ("_pgdata", "_data"):
        if base.endswith(ending):
            stem = base[: -len(ending)]
            return f"{stem}{suf}{ending}"
    return f"{base}{suf}"


def _rewrite_value(rule: dict[str, Any], *, app_id: str, env_id: str, ports: dict[str, int]) -> str:
    kind = str(rule.get("kind") or "")
    if kind == "literal":
        return str(rule.get("value", ""))
    if kind == "compose_project":
        return _compose_project(app_id, env_id)
    if kind == "container_name":
        base = str(rule.get("base") or "")
        return f"{base}{_slug_suffix(env_id)}"
    if kind == "volume":
        base = str(rule.get("base") or "")
        return _volume_name(base, env_id)
    if kind == "port":
        pk = str(rule.get("port_key") or "app")
        return str(ports.get(pk, 0))
    return ""


def render_env(
    template: dict[str, Any],
    *,
    app_id: str,
    env_id: str,
    ports: dict[str, int],
    source_env_path: Path | None = None,
) -> str:
    """Render a .env file from template rules and optional source .env.example."""
    env_id_l = str(env_id or "").strip().lower()
    is_prod = env_id_l in ("prod", "production")
    rewrites = {r["key"]: _rewrite_value(r, app_id=app_id, env_id=env_id, ports=ports) for r in template.get("env_rewrites", [])}
    rewrites["FORGE_MARKET_ENV"] = env_id_l
    if not is_prod:
        for r in template.get("dev_extra_keys", []):
            rewrites[r["key"]] = _rewrite_value(r, app_id=app_id, env_id=env_id, ports=ports)

    source_lines = _read_env_lines(source_env_path) if source_env_path else []
    seen: set[str] = set()
    out_lines: list[str] = []

    # Header for non-prod
    if not is_prod:
        out_lines.append(f"# Copy to .env beside compose.yaml on the Fleet host ({env_id.upper()} stack).")
        out_lines.append("")
        out_lines.append("# Compose identity — isolated from production forge-market-studio")
        for key in (
            "FORGE_MARKET_COMPOSE_PROJECT",
            "FORGE_MARKET_PG_CONTAINER",
            "FORGE_MARKET_APP_CONTAINER",
            "FORGE_MARKET_APP_IMAGE",
            "FORGE_MARKET_PGDATA_VOLUME",
            "FORGE_MARKET_APPDATA_VOLUME",
        ):
            if key in rewrites:
                out_lines.append(f"{key}={rewrites[key]}")
                seen.add(key)
        out_lines.append("")

    for key, val in source_lines:
        if key in rewrites:
            out_lines.append(f"{key}={rewrites[key]}")
            seen.add(key)
            continue
        if not is_prod and key in template.get("prod_only_keys", []):
            continue
        if key in seen:
            continue
        out_lines.append(f"{key}={val}")
        seen.add(key)

    for key, val in rewrites.items():
        if key not in seen:
            out_lines.append(f"{key}={val}")
            seen.add(key)

    return "\n".join(out_lines) + "\n"


def resolve_ids(template: dict[str, Any], env_id: str) -> dict[str, str]:
    suf = _slug_suffix(env_id)
    label_suffix = " (DEV)" if env_id.lower() == "dev" else (f" ({env_id.upper()})" if suf else "")
    gw = template.get("gateway", {})
    cs = template.get("container_service", {})
    slug_pat = str(gw.get("slug_pattern", "market-studio{suffix}"))
    svc_pat = str(cs.get("id_pattern", slug_pat))
    return {
        "gateway_slug": slug_pat.replace("{suffix}", suf),
        "container_service_id": svc_pat.replace("{suffix}", suf),
        "label": str(cs.get("label_pattern", "Granite Market Studio{label_suffix}")).replace("{label_suffix}", label_suffix),
    }


def default_ports_for_env(template: dict[str, Any], env_id: str) -> dict[str, int]:
    defaults = deepcopy(template.get("default_ports") or {})
    e = str(env_id or "").strip().lower()
    if e in defaults:
        return dict(defaults[e])
    return {}


def volume_names_from_template(template: dict[str, Any], env_id: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for rule in template.get("env_rewrites", []):
        if rule.get("kind") != "volume":
            continue
        key = str(rule.get("key") or "")
        val = _rewrite_value(rule, app_id=template["app_id"], env_id=env_id, ports={})
        if key == "FORGE_MARKET_PGDATA_VOLUME":
            out["pgdata"] = val
        elif key == "FORGE_MARKET_APPDATA_VOLUME":
            out["appdata"] = val
    return out
