"""Known Forge ecosystem reference: what runs where and how pieces connect.

Live placement comes from cluster nodes (managed compose services). The catalog
is the reference architecture; unmatched services stay under their node tables.
"""

from __future__ import annotations

from typing import Any

ECOSYSTEM_SCHEMA = "forge.fleet.ecosystem.v1"

# Order is the reference reading order (control → edge → products → data).
_COMPONENTS: tuple[dict[str, Any], ...] = (
    {
        "id": "fleet",
        "label": "Forge Fleet",
        "layer": "control",
        "summary": "Job and compose control plane on each node. Admin stays on the laptop.",
        "builtin": True,
        "connects_to": [],
    },
    {
        "id": "forge-llm",
        "label": "Forge LLM gateway",
        "layer": "reasoning",
        "summary": "OpenAI-compatible gateway, catalog, and local runners.",
        "type_ids": ("forge_llm",),
        "id_prefixes": ("default", "forge-llm", "llm"),
        "connects_to": [{"id": "fleet", "via": "Managed by Fleet compose"}],
    },
    {
        "id": "forge-2b",
        "label": "Forge 2B shim",
        "layer": "reasoning",
        "summary": "Conversation shim in front of the gateway.",
        "id_prefixes": ("forge-2b",),
        "connects_to": [{"id": "forge-llm", "via": "Chat completions"}],
    },
    {
        "id": "open-webui",
        "label": "Open WebUI",
        "layer": "edge",
        "summary": "Operator chat UI. Production host is Mercury (webui.forgedc.net).",
        "id_prefixes": ("open-webui",),
        "connects_to": [
            {"id": "forge-llm", "via": "Forge LLM connection"},
            {"id": "forge-2b", "via": "Optional shim connection"},
        ],
    },
    {
        "id": "market-studio",
        "label": "Forge Market Studio",
        "layer": "product",
        "summary": "Market studio app and its Postgres.",
        "id_prefixes": ("market-studio", "forge-market"),
        "connects_to": [{"id": "fleet", "via": "Rollout and health via Fleet"}],
    },
    {
        "id": "mlflow",
        "label": "MLflow",
        "layer": "product",
        "summary": "Experiment tracking stack.",
        "id_prefixes": ("mlflow",),
        "connects_to": [{"id": "fleet", "via": "Managed compose"}],
    },
    {
        "id": "agentic-dev",
        "label": "Agentic dev",
        "layer": "product",
        "summary": "Bounded repo tasks in job containers.",
        "id_prefixes": ("agentic",),
        "connects_to": [
            {"id": "fleet", "via": "Job runner"},
            {"id": "forge-llm", "via": "Optional gateway lane"},
        ],
    },
)

_LAYERS = (
    {"id": "control", "label": "Control"},
    {"id": "reasoning", "label": "Reasoning"},
    {"id": "edge", "label": "Edge"},
    {"id": "product", "label": "Products"},
)


def _svc_state(svc: dict[str, Any]) -> str:
    st = svc.get("status") if isinstance(svc.get("status"), dict) else {}
    if st.get("last_error") and not st.get("ps_ok", True):
        return "error"
    running = st.get("services_running")
    total = st.get("services_total")
    try:
        running_i = int(running) if running is not None else 0
        total_i = int(total) if total is not None else 0
    except (TypeError, ValueError):
        return "unknown"
    if total_i <= 0:
        return "registered"
    if running_i <= 0:
        return "stopped"
    if running_i >= total_i:
        return "running"
    return "partial"


def _matches(comp: dict[str, Any], svc: dict[str, Any]) -> bool:
    tid = str(svc.get("type_id") or "")
    sid = str(svc.get("id") or "")
    if tid and tid in comp.get("type_ids", ()):
        return True
    for prefix in comp.get("id_prefixes", ()):
        if sid == prefix or sid.startswith(prefix + "-") or sid.startswith(prefix):
            return True
    return False


def _placement(node: dict[str, Any], svc: dict[str, Any] | None, *, builtin: bool = False) -> dict[str, Any]:
    st = (svc or {}).get("status") if isinstance((svc or {}).get("status"), dict) else {}
    state = "up" if builtin and node.get("ok") else ("down" if builtin else _svc_state(svc or {}))
    if builtin and not node.get("ok"):
        state = "down"
    return {
        "node_label": node.get("label"),
        "node_id": node.get("node_id"),
        "scope": node.get("scope"),
        "peer_id": node.get("peer_id"),
        "service_id": None if builtin else (svc or {}).get("id"),
        "state": state,
        "services_running": None if builtin else st.get("services_running"),
        "services_total": None if builtin else st.get("services_total"),
        "last_error": None if builtin else st.get("last_error"),
    }


def ecosystem_view(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Annotate the reference catalog with live placements from cluster nodes."""
    components: list[dict[str, Any]] = []
    claimed: set[tuple[str, str]] = set()
    for comp in _COMPONENTS:
        placements: list[dict[str, Any]] = []
        if comp.get("builtin"):
            for node in nodes:
                placements.append(_placement(node, None, builtin=True))
        else:
            for node in nodes:
                for svc in node.get("services") or []:
                    if not isinstance(svc, dict) or not _matches(comp, svc):
                        continue
                    key = (str(node.get("label") or ""), str(svc.get("id") or ""))
                    claimed.add(key)
                    placements.append(_placement(node, svc))
        states = [p["state"] for p in placements]
        if not placements:
            rollup = "absent"
        elif any(s == "running" or s == "up" for s in states):
            rollup = "running" if any(s == "running" for s in states) or any(s == "up" for s in states) else "partial"
        elif any(s == "partial" for s in states):
            rollup = "partial"
        elif any(s == "error" for s in states):
            rollup = "error"
        else:
            rollup = states[0]
        components.append(
            {
                "id": comp["id"],
                "label": comp["label"],
                "layer": comp["layer"],
                "summary": comp["summary"],
                "status": rollup,
                "connects_to": list(comp.get("connects_to") or []),
                "placements": placements,
            }
        )
    other: list[dict[str, Any]] = []
    for node in nodes:
        for svc in node.get("services") or []:
            if not isinstance(svc, dict):
                continue
            key = (str(node.get("label") or ""), str(svc.get("id") or ""))
            if key in claimed:
                continue
            other.append(
                {
                    "node_label": node.get("label"),
                    "service_id": svc.get("id"),
                    "type_id": svc.get("type_id"),
                    "state": _svc_state(svc),
                }
            )
    return {
        "schema_version": ECOSYSTEM_SCHEMA,
        "layers": [dict(row) for row in _LAYERS],
        "components": components,
        "other_services": other,
    }
