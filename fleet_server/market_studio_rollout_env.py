"""Resolve Market Studio rollout identity for any env_id (prod, dev, clean, …)."""

from __future__ import annotations

from pathlib import Path

from fleet_server import env_templates


def compose_root_for_env(fleet_root: Path, env_id: str) -> Path:
    e = str(env_id or "").strip().lower()
    if e in ("prod", "production"):
        return fleet_root / "deploy" / "forge-market-studio"
    if e == "dev":
        return fleet_root / "deploy" / "forge-market-studio-dev"
    return fleet_root / "deploy" / f"market-studio-{e}"


def rollout_identity(env_id: str) -> tuple[str, str]:
    tpl = env_templates.get_template("forge_market_studio")
    if tpl is None:
        raise ValueError("template_missing")
    ids = env_templates.resolve_ids(tpl, env_id)
    return ids["container_service_id"], ids["label"]


def volume_names(env_id: str) -> tuple[str, str]:
    tpl = env_templates.get_template("forge_market_studio")
    if tpl is None:
        return "", ""
    vols = env_templates.volume_names_from_template(tpl, env_id)
    return vols.get("pgdata", ""), vols.get("appdata", "")


def host_ports(env_id: str, *, used: set[int] | None = None) -> tuple[int, int]:
    tpl = env_templates.get_template("forge_market_studio")
    if tpl is None:
        return 0, 0
    ports = env_templates.default_ports_for_env(tpl, env_id)
    if not ports:
        from fleet_server import environments

        ports = environments.allocate_ports(tpl, env_id, used=used or set())
    return int(ports.get("app", 0)), int(ports.get("postgres", 0))


def known_appdata_volumes() -> list[str]:
    tpl = env_templates.get_template("forge_market_studio")
    if tpl is None:
        return []
    out: list[str] = []
    for env_id in ("prod", "dev", "clean"):
        vols = env_templates.volume_names_from_template(tpl, env_id)
        app = vols.get("appdata")
        if app and app not in out:
            out.append(app)
    return out
