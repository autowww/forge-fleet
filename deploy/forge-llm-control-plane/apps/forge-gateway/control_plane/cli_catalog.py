"""Cursor CLI model catalog for gateway routing and GET /v1/models."""

from __future__ import annotations

import os
import subprocess
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from control_plane.cli_lane import is_cli_model as _lane_is_cli_model
from control_plane.cli_lane import normalize_model

def _catalog_candidates() -> list[Path]:
    out: list[Path] = []
    raw = (os.environ.get("FORGE_LLM_CLI_MODELS_FILE") or "").strip()
    if raw:
        out.append(Path(raw))
    out.extend(
        [
            Path("/config/cursor_cli_models.yaml"),
            Path(__file__).resolve().parents[1] / "configs" / "cursor_cli_models.yaml",
            Path(__file__).resolve().parents[3] / "configs" / "cursor_cli_models.yaml",
        ]
    )
    return out


def _catalog_path() -> Path:
    for candidate in _catalog_candidates():
        if candidate.is_file():
            return candidate
    return _catalog_candidates()[-1]


@lru_cache(maxsize=4)
def load_cursor_cli_catalog(path: str | None = None) -> dict[str, Any]:
    if yaml is None:
        return {"models": []}
    cat_path = Path(path) if path else _catalog_path()
    if not cat_path.is_file():
        return {"models": []}
    data = yaml.safe_load(cat_path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {"models": []}


def catalog_models(*, enabled_only: bool = True) -> list[dict[str, Any]]:
    rows = load_cursor_cli_catalog().get("models") or []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if enabled_only and row.get("enabled") is False:
            continue
        gid = str(row.get("gateway_id") or "").strip()
        if gid:
            out.append(row)
    return out


def _all_request_ids_for_row(row: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    gid = str(row.get("gateway_id") or "").strip()
    cid = str(row.get("cursor_id") or gid).strip()
    if gid:
        ids.add(gid)
        ids.add(normalize_model(gid))
    if cid:
        ids.add(cid)
    for alias in row.get("aliases") or []:
        if isinstance(alias, str) and alias.strip():
            ids.add(alias.strip())
            ids.add(normalize_model(alias))
    return {x for x in ids if x}


def catalog_request_id_set() -> set[str]:
    s: set[str] = set()
    for row in catalog_models(enabled_only=False):
        s |= _all_request_ids_for_row(row)
    for mid in discover_cursor_agent_model_ids():
        s.add(mid)
        s.add(normalize_model(mid))
        s.add(f"forge-llm.{mid}")
    return s


def is_catalog_cli_model(model: str) -> bool:
    name = normalize_model(model)
    if not name:
        return False
    if name in catalog_request_id_set():
        for row in catalog_models(enabled_only=False):
            if name in _all_request_ids_for_row(row):
                return row.get("enabled") is not False
        return True
    raw = (model or "").strip()
    if raw in catalog_request_id_set():
        for row in catalog_models(enabled_only=False):
            if raw in _all_request_ids_for_row(row):
                return row.get("enabled") is not False
    return False


def is_any_cli_model(model: str) -> bool:
    return _lane_is_cli_model(model) or is_catalog_cli_model(model)


def resolve_cursor_model_id(model: str) -> str:
    name = normalize_model(model)
    for row in catalog_models(enabled_only=False):
        ids = _all_request_ids_for_row(row)
        if name in ids or model.strip() in ids:
            if row.get("enabled") is False:
                continue
            return str(row.get("cursor_id") or row.get("gateway_id") or name)
    if _lane_is_cli_model(model):
        lower = name.lower()
        if lower == "composer":
            return "composer-2.5"
        if lower == "grok":
            return "grok"
        return name
    return name


def cursor_openai_model_objects(existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Append catalog CLI models to GET /v1/models (Open WebUI / Squid)."""
    by_id = {
        str(m.get("id")): m for m in existing if isinstance(m, dict) and m.get("id")
    }
    out = list(existing)
    now = int(time.time())
    overlay_rows = list(catalog_models(enabled_only=True)) + _discovered_overlay_rows()
    for row in overlay_rows:
        gid = str(row.get("gateway_id") or "")
        if not gid or gid in by_id:
            continue
        label = str(row.get("label") or gid)
        out.append(
            {
                "id": gid,
                "object": "model",
                "created": now,
                "owned_by": "forge-gateway-cursor-cli",
                "forge_cursor_lane": True,
                "forge_label": label,
                "forge_cursor_id": str(row.get("cursor_id") or gid),
            }
        )
        by_id[gid] = out[-1]
        prefixed = f"forge-llm.{gid}"
        if prefixed not in by_id:
            out.append(
                {
                    "id": prefixed,
                    "object": "model",
                    "created": now,
                    "owned_by": "forge-gateway-cursor-cli",
                    "forge_cursor_lane": True,
                    "forge_label": label,
                    "forge_cursor_id": str(row.get("cursor_id") or gid),
                    "forge_gateway_alias": gid,
                }
            )
            by_id[prefixed] = out[-1]
    return out


def discover_cursor_agent_model_ids(*, timeout: float = 15.0) -> list[str]:
    """Live ids from cursor-agent models (never appears inside that command output)."""
    if os.environ.get("FORGE_LLM_CLI_DISCOVER_MODELS", "1").strip().lower() in ("0", "false", "no"):
        return []
    binary = (os.environ.get("CURSOR_AGENT_BIN") or "cursor-agent").strip() or "cursor-agent"
    try:
        proc = subprocess.run(
            [binary, "models"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0:
        return []
    models: list[str] = []
    for line in (proc.stdout or "").splitlines():
        token = line.strip().split()[0] if line.strip() else ""
        if not token or token.startswith("-") or token.lower().startswith("error"):
            continue
        models.append(token)
    return models


def _discovered_overlay_rows() -> list[dict[str, Any]]:
    letter = str(load_cursor_cli_catalog().get("display_prefix_letter") or "F")
    known = {str(r.get("gateway_id")) for r in catalog_models(enabled_only=False)}
    known |= {str(r.get("cursor_id")) for r in catalog_models(enabled_only=False)}
    rows: list[dict[str, Any]] = []
    for mid in discover_cursor_agent_model_ids():
        if mid in known:
            continue
        rows.append(
            {
                "gateway_id": mid,
                "cursor_id": mid,
                "label": f"{letter} {mid} (discovered)",
                "family": mid.split("-", 1)[0] if "-" in mid else mid,
                "enabled": True,
                "aliases": [f"forge-llm.{mid}"],
                "notes": "Auto from cursor-agent models; not in static YAML",
                "discovered": True,
            }
        )
    return rows


def catalog_for_api() -> dict[str, Any]:
    cat = load_cursor_cli_catalog()
    rows = []
    for row in catalog_models(enabled_only=False):
        rows.append(
            {
                "gateway_id": row.get("gateway_id"),
                "cursor_id": row.get("cursor_id"),
                "label": row.get("label"),
                "family": row.get("family"),
                "enabled": row.get("enabled", True),
                "aliases": row.get("aliases") or [],
                "notes": row.get("notes"),
                "discovered": False,
            }
        )
    discovered = _discovered_overlay_rows()
    static_ids = {str(r.get("gateway_id")) for r in rows}
    for row in discovered:
        if row.get("gateway_id") not in static_ids:
            rows.append(row)
    live = discover_cursor_agent_model_ids()
    return {
        "schema": cat.get("schema"),
        "display_prefix_letter": cat.get("display_prefix_letter"),
        "endpoints": cat.get("endpoints") or {},
        "models": rows,
        "cursor_agent_models_live": live,
        "overlay_note": (
            "Forge F-label overlays are gateway GET /v1/models and GET /v1/llm/cursor/models — "
            "they are not listed by cursor-agent models"
        ),
    }