"""Fleet container template library — contracts Lenses / Studio can target."""

from __future__ import annotations

from typing import Any

from fleet_server.versioning import FLEET_TEMPLATE_LIB_VERSION

# ``probe_contract`` matches ``forge-lenses/lenses/sandbox/host_cpu_probe.py`` JSON line protocol.
TEMPLATE_LIB: list[dict[str, Any]] = [
    {
        "id": "host_cpu_probe",
        "title": "Host CPU probe",
        "container_class": "host_cpu_probe",
        "status": "stable",
        "probe_contract": "lenses.sandbox.host_cpu_probe@v1",
        "notes": "Mounts host /proc read-only; one JSON stdout line with cpu_usage_pct (host busy %).",
    },
    {
        "id": "forge_agent",
        "title": "Forge agent (generic git + script)",
        "container_class": "forge_agent",
        "status": "planned",
        "env": ["GITPATH", "GIT_URL", "GIT_REF"],
        "notes": (
            "Clone + run user script with GITPATH set; signal Fleet on completion; container must stay alive until "
            "Lenses calls POST /v1/containers/dispose with the recorded container id (no auto --rm for that mode)."
        ),
    },
    {
        "id": "forge_llm_console",
        "title": "Forge LLM (Compose stack + console)",
        "container_class": "forge_llm",
        "status": "stable",
        "config_paths": {
            "types": "$FLEET_DATA_DIR/etc/containers/types.json",
            "services": "$FLEET_DATA_DIR/etc/services/<id>.json",
        },
        "fleet_api": {
            "types": "GET /v1/container-types",
            "list_services": "GET /v1/container-services",
            "get_service": "GET /v1/container-services/{id}",
            "add_service": "POST /v1/container-services",
            "update_service": "PUT /v1/container-services/{id}",
            "delete_service": "DELETE /v1/container-services/{id}",
            "start": "POST /v1/container-services/{id}/start",
            "stop": "POST /v1/container-services/{id}/stop",
            "legacy_status": "GET /v1/services/forge-llm",
            "legacy_start_stop": "POST /v1/services/forge-llm/start|stop (primary service id)",
        },
        "env": ["FLEET_DATA_DIR", "FLEET_FORGE_LLM_ROOT", "FLEET_FORGE_LLM_COMPOSE_FILES", "FLEET_FORGE_CONSOLE_URL"],
        "notes": (
            "Managed stacks are defined on disk under the same ``--data-dir`` as ``fleet.sqlite`` (install scripts: "
            "``FLEET_USER_DATA`` / ``FLEET_DATA``). ``FLEET_FORGE_LLM_ROOT`` seeds ``etc/services/default.json`` once "
            "when no services exist. Start/stop always use the compose_files saved in each service JSON."
        ),
    },
]


def templates_payload() -> dict[str, Any]:
    return {
        "ok": True,
        "template_lib_version": FLEET_TEMPLATE_LIB_VERSION,
        "templates": list(TEMPLATE_LIB),
    }
