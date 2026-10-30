"""Route metadata for request guard (scope, rate class, auth)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

RouteClass = Literal["read", "mutate", "heavy", "public", "proxy"]
Scope = Literal[
    "public",
    "admin",
    "read:capacity",
    "read:profile",
    "read:telemetry",
    "read:links",
    "mesh:advise",
    "workspace",
]


@dataclass(frozen=True)
class RouteSpec:
    pattern: re.Pattern[str]
    methods: frozenset[str]
    scope: Scope
    route_class: RouteClass
    name: str


def _p(regex: str) -> re.Pattern[str]:
    return re.compile("^" + regex + "$")


# Prefix routes registered before the catch-all unknown handler.
ROUTE_SPECS: tuple[RouteSpec, ...] = (
    RouteSpec(_p("/v1/health"), frozenset({"GET"}), "public", "public", "health"),
    RouteSpec(_p("/v1/host/link-probe"), frozenset({"GET"}), "read:links", "heavy", "link_probe"),
    RouteSpec(_p("/v1/auth/session"), frozenset({"POST"}), "public", "mutate", "auth_session"),
    RouteSpec(_p("/v1/auth/sessions"), frozenset({"GET"}), "admin", "read", "auth_sessions_list"),
    RouteSpec(_p("/v1/auth/session/[^/]+"), frozenset({"DELETE"}), "admin", "mutate", "auth_session_delete"),
    RouteSpec(_p("/v1/host/profile"), frozenset({"GET"}), "read:profile", "read", "host_profile_get"),
    RouteSpec(_p("/v1/host/profile/benchmark"), frozenset({"POST"}), "admin", "heavy", "host_profile_bench"),
    RouteSpec(_p("/v1/host/profile/fmsbench"), frozenset({"POST"}), "admin", "heavy", "host_profile_fmsbench"),
    RouteSpec(_p("/v1/host/profile/fmsbench/cleanup"), frozenset({"POST"}), "admin", "mutate", "host_profile_fmsbench_cleanup"),
    RouteSpec(_p("/v1/remote-peers/[^/]+/host/profile/fmsbench/cleanup"), frozenset({"POST"}), "admin", "mutate", "remote_fmsbench_cleanup"),
    RouteSpec(_p("/v1/mesh/benchmarks"), frozenset({"GET"}), "read:profile", "read", "mesh_benchmarks"),
    RouteSpec(_p("/v1/mesh/benchmarks/run"), frozenset({"POST"}), "admin", "heavy", "mesh_benchmarks_run"),
    RouteSpec(_p("/v1/capacity"), frozenset({"GET"}), "read:capacity", "read", "capacity"),
    RouteSpec(_p("/v1/mesh/capacity"), frozenset({"GET"}), "read:capacity", "read", "mesh_capacity"),
    RouteSpec(_p("/v1/mesh/links"), frozenset({"GET"}), "read:links", "read", "mesh_links"),
    RouteSpec(
        _p("/v1/mesh/offload/advise"),
        frozenset({"POST"}),
        "mesh:advise",
        "mutate",
        "mesh_offload_advise",
    ),
    RouteSpec(
        _p("/v1/admin/security/events"),
        frozenset({"GET"}),
        "admin",
        "read",
        "security_events",
    ),
    RouteSpec(
        _p("/v1/admin/security/blocks"),
        frozenset({"GET", "POST"}),
        "admin",
        "mutate",
        "security_blocks",
    ),
    RouteSpec(
        _p("/v1/admin/security/agent"),
        frozenset({"GET"}),
        "admin",
        "read",
        "security_agent_status",
    ),
    RouteSpec(
        _p("/v1/admin/security/agent/test"),
        frozenset({"POST"}),
        "admin",
        "mutate",
        "security_agent_test",
    ),
    RouteSpec(_p("/v1/jobs"), frozenset({"POST"}), "admin", "mutate", "jobs_create"),
    RouteSpec(_p("/v1/admin/cursor-cli"), frozenset({"POST"}), "admin", "heavy", "admin_cursor_cli"),
    RouteSpec(_p("/v1/admin/temp-jobs"), frozenset({"POST"}), "admin", "mutate", "admin_temp_jobs_submit"),
    RouteSpec(_p("/v1/admin/temp-jobs/[^/]+/result"), frozenset({"GET"}), "admin", "read", "admin_temp_jobs_result"),
    RouteSpec(_p("/v1/admin/temp-jobs/[^/]+"), frozenset({"GET"}), "admin", "read", "admin_temp_jobs_status"),
    RouteSpec(_p("/v1/admin/agentic-dev-task"), frozenset({"POST"}), "admin", "heavy", "admin_agentic_dev_submit"),
    RouteSpec(_p("/v1/admin/code-review-task"), frozenset({"POST"}), "admin", "heavy", "admin_code_review_submit"),
    RouteSpec(_p("/v1/admin/agentic-dev-task/[^/]+/credential"), frozenset({"POST"}), "admin", "mutate", "admin_agentic_dev_credential"),
    RouteSpec(_p("/v1/admin/agentic-dev-task/[^/]+"), frozenset({"GET"}), "admin", "read", "admin_agentic_dev_get"),
    RouteSpec(_p("/v1/admin/agentic-dev/capacity"), frozenset({"GET"}), "admin", "read", "admin_agentic_dev_capacity"),
    RouteSpec(_p("/v1/admin/agentic-dev/branch-gc"), frozenset({"POST"}), "admin", "mutate", "admin_agentic_dev_branch_gc"),
    RouteSpec(_p("/v1/admin/agentic-dev/pending-credentials"), frozenset({"GET"}), "admin", "read", "admin_agentic_dev_pending"),
    RouteSpec(_p("/v1/admin/forge-agents-roadrunner-rollout"), frozenset({"POST"}), "admin", "heavy", "admin_forge_agents_rollout"),
    RouteSpec(_p("/v1/admin/forge-agents-roadrunner-rollout-log"), frozenset({"GET"}), "admin", "read", "admin_forge_agents_rollout_log"),
    RouteSpec(_p("/v1/admin/cursor-cli/status"), frozenset({"GET"}), "admin", "read", "admin_cursor_cli_status"),
    RouteSpec(_p("/v1/admin/git-identity"), frozenset({"GET"}), "admin", "read", "admin_git_identity"),
    RouteSpec(_p("/v1/admin/upgrade"), frozenset({"POST"}), "admin", "heavy", "admin_upgrade"),
    RouteSpec(
        _p("/v1/remote-peers/[^/]+/admin/upgrade"),
        frozenset({"POST"}),
        "admin",
        "heavy",
        "remote_peer_upgrade",
    ),
    RouteSpec(
        _p("/v1/remote-peers/[^/]+/admin/upgrade/status"),
        frozenset({"GET"}),
        "admin",
        "read",
        "remote_peer_upgrade_status",
    ),
    RouteSpec(
        _p("/v1/remote-peers/[^/]+/lifecycle/resume"),
        frozenset({"POST"}),
        "admin",
        "mutate",
        "remote_peer_lifecycle_resume",
    ),
    RouteSpec(
        _p("/v1/operator/ui-settings"),
        frozenset({"GET", "PUT"}),
        "admin",
        "read",
        "operator_ui_settings",
    ),
    RouteSpec(
        _p("/v1/admin/edge-cache/sync"),
        frozenset({"POST"}),
        "admin",
        "mutate",
        "edge_cache_sync",
    ),
    RouteSpec(
        _p("/v1/services/[^/]+/vision"),
        frozenset({"GET"}),
        "read:profile",
        "read",
        "service_vision",
    ),
)


# Product UI served through Fleet (`/v1/app-gateways/<id>/api/...`). Not the gateway catalog.
_GATEWAY_PROXY = re.compile(r"^/v1/app-gateways/[^/]+/.+")


def match_route(path: str, method: str) -> RouteSpec | None:
    m = method.upper()
    for spec in ROUTE_SPECS:
        if m in spec.methods and spec.pattern.match(path):
            return spec
    return None


def route_class_for_path(path: str, method: str, default: RouteClass = "read") -> RouteClass:
    bare = path.split("?", 1)[0]
    if _GATEWAY_PROXY.match(bare):
        return "proxy"
    spec = match_route(path, method)
    if spec is not None:
        return spec.route_class
    if path.startswith("/v1/"):
        if method.upper() in {"POST", "PUT", "DELETE", "PATCH"}:
            return "mutate"
        return default
    return default


def scope_for_path(path: str, method: str) -> Scope:
    spec = match_route(path, method)
    if spec is not None:
        return spec.scope
    if path.startswith("/v1/admin/"):
        return "admin"
    if path.startswith("/v1/"):
        return "read:capacity"
    return "public"
