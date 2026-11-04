"""Operate forge-llm **managed** Docker Compose stacks (``docker compose`` CLI)."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from fleet_server import managed_compose_service as mcs

# Re-export generic compose helpers for backward compatibility.
resolve_compose_files = mcs.resolve_compose_files
compose_ps = mcs.compose_ps
start_for_record = mcs.start_for_record
stop_for_record = mcs.stop_for_record
compose_argv = mcs.compose_argv

_TOKENS_RATE_LOCK = threading.Lock()
_TOKENS_RATE_STATE: dict[str, tuple[float, int]] = {}


_GATEWAY_BEARER_ENV_KEYS = (
    "FORGE_API_TOKEN",
    "LLM_BEARER_TOKEN",
    "FORGE_LLM_GATEWAY_BEARER",
    "LLM_API_KEY",
    "FLEET_WAKE_BEARER_TOKEN",
)


def _first_key_from_env_file(path: Path, keys: tuple[str, ...]) -> str:
    if not path.is_file():
        return ""
    found: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        if k in keys and k not in found:
            found[k] = v.strip().strip('"').strip("'")
    for k in keys:
        if found.get(k):
            return found[k]
    return ""


def _gateway_scrape_bearer(compose_root: Path | None = None) -> str:
    """
    Bearer the Fleet host uses to scrape forge-gateway on loopback.

    Order: process env → Fleet user env (``forge-fleet.env``: ``LLM_BEARER_TOKEN`` on Granite)
    → the service compose ``.env`` (``FORGE_API_TOKEN`` written by the rollout) → the
    Open WebUI connection env. The gateway accepts the same token for all of these.
    """
    for key in _GATEWAY_BEARER_ENV_KEYS:
        val = str(os.environ.get(key) or "").strip()
        if val:
            return val
    cfg_home = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    candidates: list[tuple[Path, tuple[str, ...]]] = [
        (cfg_home / "forge-fleet" / "forge-fleet.env", _GATEWAY_BEARER_ENV_KEYS),
    ]
    if compose_root is not None:
        candidates.append((Path(compose_root) / ".env", ("FORGE_API_TOKEN", "LLM_API_KEY", "FLEET_WAKE_BEARER_TOKEN")))
    candidates.append((cfg_home / "forge-open-webui" / "forge-llm-gateway.env", ("FORGE_LLM_GATEWAY_BEARER",)))
    for path, keys in candidates:
        val = _first_key_from_env_file(path, keys)
        if val:
            return val
    return ""


def _gateway_get_json_detailed(
    path: str,
    host_port: int,
    *,
    timeout: float,
    compose_root: Path | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(json, error)``; ``error`` is a short machine-readable reason when ``json`` is None."""
    import urllib.error
    import urllib.request

    url = f"http://127.0.0.1:{int(host_port)}{path}"
    headers: dict[str, str] = {"Accept": "application/json"}
    bearer = _gateway_scrape_bearer(compose_root)
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:  # noqa: BLE001
            body = ""
        hint = " (no gateway bearer resolved on Fleet host)" if exc.code == 401 and not bearer else ""
        return None, f"gateway_http_{exc.code}{hint}: {body}".strip()
    except (OSError, urllib.error.URLError) as exc:
        return None, f"gateway_unreachable: {exc}"[:400]
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None, "gateway_invalid_json"
    if not isinstance(data, dict):
        return None, "gateway_invalid_json"
    return data, None


def _gateway_get_json(
    path: str,
    host_port: int,
    *,
    timeout: float,
    compose_root: Path | None = None,
) -> dict[str, Any] | None:
    data, _err = _gateway_get_json_detailed(path, host_port, timeout=timeout, compose_root=compose_root)
    return data


def gateway_host_port_from_compose_ps(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """
    Parse ``docker compose ps --format json`` rows for ``forge-gateway`` published ``8080`` port.

    Typical ``Ports`` string: ``0.0.0.0:18080->8080/tcp`` or ``[::]:18080->8080/tcp``.
    """
    pat = re.compile(
        r"(?:^|[\s,])(?:0\.0\.0\.0|\:\:|\:\:\:|127\.0\.0\.1)\:(\d+)->8080/(?:tcp|udp)",
        re.I,
    )
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("Service") or row.get("Name") or "").lower()
        if "forge-gateway" not in name and "gateway" not in name:
            continue
        ports = str(row.get("Ports") or "")
        m = pat.search(ports)
        if not m:
            continue
        try:
            hp = int(m.group(1))
        except ValueError:
            continue
        return {"host_port": hp, "container_port": 8080, "ports_preview": ports[:240]}
    return None


def fetch_gateway_control_plane(
    host_port: int,
    *,
    hours: float = 1.0,
    timeout: float = 3.0,
    compose_root: Path | None = None,
) -> dict[str, Any] | None:
    """Best-effort scrape of forge-gateway ``/v1/llm/stats`` from Fleet host."""
    window = max(0.01, float(hours))
    return _gateway_get_json(f"/v1/llm/stats?hours={window}", host_port, timeout=timeout, compose_root=compose_root)


def fetch_gateway_catalog(
    host_port: int,
    *,
    timeout: float = 5.0,
    compose_root: Path | None = None,
) -> dict[str, Any] | None:
    """Best-effort scrape of forge-gateway ``/v1/llm/catalog`` from Fleet host."""
    return _gateway_get_json("/v1/llm/catalog", host_port, timeout=timeout, compose_root=compose_root)


def fetch_gateway_catalog_detailed(
    host_port: int,
    *,
    timeout: float = 5.0,
    compose_root: Path | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Like :func:`fetch_gateway_catalog` but also returns the failure reason."""
    return _gateway_get_json_detailed("/v1/llm/catalog", host_port, timeout=timeout, compose_root=compose_root)


def tokens_per_sec(service_id: str, completion_tokens: int) -> float | None:
    now = time.time()
    with _TOKENS_RATE_LOCK:
        prev = _TOKENS_RATE_STATE.get(service_id)
        _TOKENS_RATE_STATE[service_id] = (now, int(completion_tokens))
    if not prev:
        return None
    dt = now - prev[0]
    if dt <= 0:
        return None
    delta = int(completion_tokens) - prev[1]
    if delta < 0:
        return None
    return round(delta / dt, 2)


def build_llm_rack(
    control_plane: dict[str, Any],
    *,
    service_id: str,
    rollup_1h: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rollup = control_plane.get("rollup") if isinstance(control_plane.get("rollup"), dict) else {}
    active = control_plane.get("active") if isinstance(control_plane.get("active"), dict) else {}
    r1 = rollup_1h if isinstance(rollup_1h, dict) else rollup
    completion_tokens = int(rollup.get("completion_tokens") or 0)
    return {
        "active_model": active.get("active_model"),
        "active_mode": active.get("active_mode"),
        "queue_depth": control_plane.get("queue_depth"),
        "requests_1h": r1.get("requests"),
        "avg_total_ms_1h": r1.get("avg_total_ms"),
        "swaps_1h": r1.get("swaps"),
        "requests_since_fleet_start": rollup.get("requests"),
        "prompt_tokens_since_fleet_start": rollup.get("prompt_tokens"),
        "completion_tokens_since_fleet_start": completion_tokens,
        "tokens_per_sec": tokens_per_sec(service_id, completion_tokens),
    }


def status_for_record(
    record: dict[str, Any],
    *,
    fleet_started_epoch: float | None = None,
) -> dict[str, Any]:
    out = mcs.status_for_record(record)
    root = Path(str(out.get("compose_root") or "")).resolve()
    rel = list(out.get("compose_files") or [])
    if not rel:
        raw_cf = record.get("compose_files")
        extras = [str(x) for x in raw_cf] if isinstance(raw_cf, list) else []
        rel = mcs.resolve_compose_files(root, extras)
    rows, _err = mcs.compose_ps(root, rel)
    gw = gateway_host_port_from_compose_ps(rows)
    if gw:
        out["gateway_publish"] = gw
        port = int(gw["host_port"])
        uptime_h = 1.0
        if fleet_started_epoch is not None:
            uptime_h = max(0.01, (time.time() - float(fleet_started_epoch)) / 3600.0)
        cp_start = fetch_gateway_control_plane(port, hours=uptime_h, compose_root=root)
        cp_1h = cp_start
        if uptime_h > 1.05:
            cp_1h = fetch_gateway_control_plane(port, hours=1.0, compose_root=root) or cp_start
        if cp_start:
            cp_start = dict(cp_start)
            if cp_1h and cp_1h is not cp_start:
                r1 = cp_1h.get("rollup") if isinstance(cp_1h.get("rollup"), dict) else {}
                cp_start["rollup_1h"] = r1
            out["control_plane"] = cp_start
    return out


def root_from_env() -> Path | None:
    raw = str(os.environ.get("FLEET_FORGE_LLM_ROOT") or "").strip()
    if not raw:
        return None
    p = Path(raw).expanduser().resolve()
    if not p.is_dir() or not (p / "compose.yaml").is_file():
        return None
    return p
