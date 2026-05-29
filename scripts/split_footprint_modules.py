#!/usr/bin/env python3
"""Mechanical split for code-footprint violations (run from forge-fleet repo root)."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FLEET = REPO / "fleet_server"


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines(keepends=True)


def _write_slice(path: Path, lines: list[str], start: int, end: int, header: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "".join(lines[start:end]), encoding="utf-8")


def _pkg_init(pkg: Path, exports: list[tuple[str, list[str]]]) -> None:
    parts = ['"""Package — see module README.md."""\n\n']
    all_names: list[str] = []
    for mod, names in exports:
        star = ", ".join(names)
        parts.append(f"from fleet_server.{pkg.name}.{mod} import {star}\n")
        all_names.extend(names)
    parts.append("\n__all__ = [\n")
    for n in all_names:
        parts.append(f'    "{n}",\n')
    parts.append("]\n")
    (pkg / "__init__.py").write_text("".join(parts), encoding="utf-8")


def split_main_http() -> None:
    main_path = FLEET / "main.py"
    src = main_path.read_text(encoding="utf-8")
    rx = re.compile(r"^    def (do_(?:GET|POST|PUT|DELETE))\(self\) -> None:", re.M)
    matches = list(rx.finditer(src))
    if len(matches) != 4:
        raise SystemExit(f"expected 4 HTTP verbs, found {len(matches)}")

    main_start = src.find("\ndef main()")
    class_start = src.find("class FleetHandler")
    helpers_end = matches[0].start()

    http = FLEET / "http"
    routes_dir = http / "routes"
    if http.exists():
        shutil.rmtree(http)
    routes_dir.mkdir(parents=True)

    shared_header = '''from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from fleet_server import (
    container_layout,
    container_templates,
    forge_llm_service,
    host_stats,
    runner,
    self_update,
    store,
    telemetry_periods,
    templates_catalog,
    thermal_llm_policy,
    versioning,
    workspace_bundle,
)
from fleet_server.test_fleet import spawn_test_fleet


def json_bytes(obj: Any) -> bytes:
    return json.dumps(obj).encode("utf-8")


'''

    helpers = src[class_start:helpers_end].replace("class FleetHandler", "class FleetHandlerBase", 1)
    helpers = helpers.replace("_json_bytes", "json_bytes")
    (http / "base.py").write_text(
        '"""FleetHandler helpers and response utilities."""\n\n' + shared_header + helpers,
        encoding="utf-8",
    )

    verb_map = {
        "do_GET": ("get.py", "GetRoutesMixin"),
        "do_POST": ("post.py", "PostRoutesMixin"),
        "do_PUT": ("put.py", "PutRoutesMixin"),
        "do_DELETE": ("delete.py", "DeleteRoutesMixin"),
    }
    imports: list[str] = []
    for i, m in enumerate(matches):
        do_name = m.group(1)
        fname, mixin = verb_map[do_name]
        body = src[m.start() : matches[i + 1].start() if i + 1 < len(matches) else main_start]
        method_body = body.replace(f"    def {do_name}(self)", f"    def {do_name}(self)", 1)
        (routes_dir / fname).write_text(
            f'"""HTTP {do_name[3:]} routes."""\n\n'
            + shared_header
            + f"from fleet_server.http.base import FleetHandlerBase\n\n\n"
            + f"class {mixin}:\n"
            + method_body
            + "\n",
            encoding="utf-8",
        )
        mod = fname[:-3]
        imports.append(f"from fleet_server.http.routes.{mod} import {mixin}")

    (http / "handler.py").write_text(
        '"""Composed Fleet HTTP handler."""\n\n'
        "from __future__ import annotations\n\n"
        "from fleet_server.http.base import FleetHandlerBase\n"
        + "\n".join(imports)
        + "\n\n\n"
        "class FleetHandler(\n"
        "    GetRoutesMixin,\n"
        "    PostRoutesMixin,\n"
        "    PutRoutesMixin,\n"
        "    DeleteRoutesMixin,\n"
        "    FleetHandlerBase,\n"
        "):\n"
        '    """Route bodies live in ``fleet_server.http.routes``."""\n\n'
        "    pass\n",
        encoding="utf-8",
    )
    (http / "__init__.py").write_text(
        'from fleet_server.http.handler import FleetHandler\n\n__all__ = ["FleetHandler"]\n',
        encoding="utf-8",
    )
    (http / "README.md").write_text(
        "# Fleet HTTP layer\n\n"
        "- `base.py` — auth, JSON/static helpers\n"
        "- `routes/` — `do_GET` / `do_POST` / `do_PUT` / `do_DELETE` mixins\n"
        "- `handler.py` — composed `FleetHandler`\n",
        encoding="utf-8",
    )

    tail = src[main_start + 1 :]  # skip leading newline before def main
    main_path.write_text(
        '"""CLI entry: ``python -m fleet_server``."""\n\n'
        "from __future__ import annotations\n\n"
        "import argparse\n"
        "import os\n"
        "import threading\n"
        "import time\n"
        "from datetime import UTC, datetime\n"
        "from http.server import ThreadingHTTPServer\n"
        "from pathlib import Path\n\n"
        "from fleet_server import container_layout, container_templates, store, workspace_bundle\n"
        "from fleet_server.http import FleetHandler\n\n\n"
        "def _loopback_bind_only(host: str) -> bool:\n"
        '    h = (host or "").strip().lower()\n'
        "    return h in (\"127.0.0.1\", \"::1\", \"localhost\")\n\n\n"
        + tail,
        encoding="utf-8",
    )
    print("split main.py -> http/")


def split_host_stats() -> None:
    path = FLEET / "host_stats.py"
    lines = _lines(path)
    header = "".join(lines[:37])
    pkg = FLEET / "host_stats"
    if pkg.exists():
        shutil.rmtree(pkg)
    pkg.mkdir()
    _write_slice(pkg / "gpu.py", lines, 37, 422, header)
    _write_slice(pkg / "energy_cpu.py", lines, 422, 731, header)
    _write_slice(pkg / "disk_thermal.py", lines, 731, len(lines), header)
    _pkg_init(
        pkg,
        [
            ("gpu", ["nvidia_gpu_snapshot", "amdgpu_sysfs_snapshot", "amdgpu_junction_snapshot",
                     "linux_soc_junction_rated_sysfs", "intel_engine_busy_snapshot",
                     "rocm_smi_snapshot", "gpu_bundle"]),
            ("energy_cpu", ["rapl_package_energy_uj", "rapl_package_power_uw_sum", "energy_observation",
                            "cpu_usage_percent_sample", "cpu_usage_percent_per_core_avg_sample",
                            "physical_cpu_cores_linux", "cpufreq_metrics", "_per_cpu_jiffies_line"]),
            ("disk_thermal", ["disk_io_snapshot", "disk_space_snapshot", "thermal_cpu_snapshot", "snapshot"]),
        ],
    )
    (pkg / "README.md").write_text("# host_stats\n\nLinux host metrics (stdlib only).\n", encoding="utf-8")
    path.unlink()
    print("split host_stats.py -> host_stats/")


def split_store() -> None:
    path = FLEET / "store.py"
    lines = _lines(path)
    header = "".join(lines[:18])
    pkg = FLEET / "store"
    if pkg.exists():
        shutil.rmtree(pkg)
    pkg.mkdir()
    _write_slice(pkg / "schema.py", lines, 18, 193, header)
    _write_slice(pkg / "jobs.py", lines, 193, 475, header)
    _write_slice(pkg / "telemetry.py", lines, 475, len(lines), header)
    _pkg_init(
        pkg,
        [
            ("schema", ["connect", "get_fleet_version_row"]),
            ("jobs", [
                "insert_job", "update_job", "get_job", "authenticate_workspace_worker_bridge",
                "merge_job_meta", "merge_worker_progress", "set_worker_result",
                "sum_accounted_core_seconds", "count_jobs_by_status",
                "count_running_jobs_by_container_class", "workload_title_for_job",
                "count_jobs", "list_jobs_summary",
            ]),
            ("telemetry", [
                "telemetry_time_bounds", "get_energy_ledger", "apply_energy_ledger_delta",
                "maybe_record_telemetry_sample", "list_telemetry_samples",
                "insert_cooldown_event", "cooldown_time_bounds", "cooldown_aggregate_s",
                "cooldown_summary_payload", "cooldown_summary_presets",
            ]),
        ],
    )
    (pkg / "README.md").write_text("# store\n\nSQLite persistence for jobs, telemetry, cooldown.\n", encoding="utf-8")
    path.unlink()
    print("split store.py -> store/")


def split_container_templates() -> None:
    path = FLEET / "container_templates.py"
    lines = _lines(path)
    header = "".join(lines[:36])
    pkg = FLEET / "container_templates"
    if pkg.exists():
        shutil.rmtree(pkg)
    pkg.mkdir()
    _write_slice(pkg / "catalog.py", lines, 36, 360, header)
    _write_slice(pkg / "build.py", lines, 360, 631, header)
    _write_slice(pkg / "api.py", lines, 631, len(lines), header)
    _pkg_init(
        pkg,
        [
            ("catalog", [
                "requirement_templates_file", "build_cache_file", "dockerfiles_allow_root",
                "ensure_template_layout", "load_requirement_templates", "load_build_cache",
                "save_requirement_templates", "validate_requirement_id", "template_by_id",
                "bundle_fingerprint", "max_template_package_upload_bytes",
                "apply_requirement_template_package", "copy_default_templates",
            ]),
            ("build", [
                "prefetch_template_images_enabled", "prefetch_requirement_template_images",
                "parse_build_if_missing_query", "meta_build_template_if_missing",
                "resolve_cached_image", "run_template_build",
            ]),
            ("api", [
                "templates_api_payload", "status_api_payload", "resolve_api_payload",
                "inject_template_image_into_docker_argv",
            ]),
        ],
    )
    (pkg / "README.md").write_text("# container_templates\n\nRequirement template images and API payloads.\n", encoding="utf-8")
    path.unlink()
    print("split container_templates.py -> container_templates/")


def split_container_layout() -> None:
    path = FLEET / "container_layout.py"
    lines = _lines(path)
    header = "".join(lines[:37])
    pkg = FLEET / "container_layout"
    if pkg.exists():
        shutil.rmtree(pkg)
    pkg.mkdir()
    _write_slice(pkg / "paths.py", lines, 36, 302, header)
    _write_slice(pkg / "services.py", lines, 302, 515, header)
    _write_slice(pkg / "types.py", lines, 515, len(lines), header)
    _pkg_init(
        pkg,
        [
            ("paths", [
                "fleet_data_dir_from_server", "etc_root", "types_file", "services_dir",
                "service_file", "layout_paths_payload", "ensure_layout", "load_types",
                "types_api_payload", "type_by_id", "effective_type_by_id",
            ]),
            ("services", [
                "validate_service_id", "allocate_forge_llm_service_id", "list_service_records",
                "read_service", "delete_service", "upsert_service", "update_service",
                "orchestration_metrics_snapshot", "services_status_snapshot",
                "service_ids_for_type_id",
            ]),
            ("types", [
                "validate_type_id", "validate_container_class", "validate_types_document",
                "save_types_document", "add_type_row", "update_type_row", "delete_type_row",
                "pick_primary_forge_llm_service_id",
            ]),
        ],
    )
    (pkg / "README.md").write_text("# container_layout\n\nContainer types and compose services on disk.\n", encoding="utf-8")
    path.unlink()
    print("split container_layout.py -> container_layout/")


def split_admin_html() -> None:
    admin = FLEET / "static" / "admin.html"
    text = admin.read_text(encoding="utf-8")
    static_dir = FLEET / "static" / "admin"
    static_dir.mkdir(exist_ok=True)

    style_m = re.search(
        r'<style id="fleet-overview-tile-row-fallback">(.*?)</style>',
        text,
        re.DOTALL,
    )
    if style_m:
        (static_dir / "tile-row-fallback.css").write_text(style_m.group(1).strip() + "\n", encoding="utf-8")
        text = text.replace(style_m.group(0), '<link rel="stylesheet" href="/admin/static/tile-row-fallback.css" />')

    theme_m = re.search(r"  <script>\n  /\* forge-theme\.js only.*?</script>\n", text, re.DOTALL)
    if theme_m:
        inner = theme_m.group(0)[len("  <script>\n") : -len("\n  </script>\n")]
        (static_dir / "theme-boot.js").write_text(inner, encoding="utf-8")
        text = text.replace(theme_m.group(0), '  <script src="/admin/static/theme-boot.js"></script>\n')

    app_start = text.find('  <script>\n  (function () {\n    "use strict";')
    app_end = text.rfind("  </script>\n</body>")
    if app_start < 0 or app_end < 0:
        raise SystemExit("admin app script markers not found")
    app_js = text[app_start + len("  <script>\n") : app_end]
    (static_dir / "app.js").write_text(app_js, encoding="utf-8")
    text = text[:app_start] + '  <script src="/admin/static/app.js"></script>\n' + text[app_end + len("  </script>\n") :]

    admin.write_text(text, encoding="utf-8")
    (static_dir / "README.md").write_text(
        "# Admin static assets\n\nServed under `/admin/static/` via FleetHandler.\n",
        encoding="utf-8",
    )
    print(f"split admin.html ({len(admin.read_text().splitlines())} lines) + static/admin/*")


def split_openapi() -> None:
    import sys

    sys.path.insert(0, str(REPO / "scripts"))
    from openapi_fragments import bundle_openapi, load_openapi_doc, write_openapi_fragments

    oapi_path = REPO / "docs" / "schemas" / "openapi.json"
    if oapi_path.is_file():
        doc = json.loads(oapi_path.read_text(encoding="utf-8"))
    else:
        doc = load_openapi_doc()

    frag_dir = REPO / "docs" / "schemas" / "openapi"
    if frag_dir.exists():
        shutil.rmtree(frag_dir)

    write_openapi_fragments(doc)
    paths_count = len(list((frag_dir / "paths").glob("*.json")))
    (frag_dir / "README.md").write_text(
        "# OpenAPI fragments\n\n"
        "Edit `paths/*.json`, `components.json`, and `openapi-root.json` (not the bundled file).\n\n"
        "Regenerate the deploy/CI bundle:\n\n"
        "```bash\npython3 scripts/bundle_openapi.py\n```\n\n"
        "Writes `../openapi.json` (generated; prefer editing fragments here).\n",
        encoding="utf-8",
    )
    bundle_openapi()
    print(f"split openapi -> {paths_count} path fragments")


def bundle_openapi() -> None:
    import sys

    sys.path.insert(0, str(REPO / "scripts"))
    from openapi_fragments import bundle_openapi as _bundle

    _bundle()


def main() -> None:
    split_main_http()
    split_host_stats()
    split_store()
    split_container_templates()
    split_container_layout()
    split_admin_html()
    split_openapi()
    print("footprint split complete")


if __name__ == "__main__":
    main()
