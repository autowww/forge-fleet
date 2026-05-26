"""CLI entry: ``python -m fleet_server``."""

from __future__ import annotations

import argparse
import os
import threading
import time
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path

from fleet_server import container_layout, container_templates, store, workspace_bundle
from fleet_server.http import FleetHandler


def _loopback_bind_only(host: str) -> bool:
    h = (host or "").strip().lower()
    return h in ("127.0.0.1", "::1", "localhost")


def main() -> None:
    ap = argparse.ArgumentParser(description="Forge Fleet HTTP server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=18765)
    ap.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("FLEET_DATA_DIR") or ".fleet-data"),
        help="Directory for fleet.sqlite",
    )
    args = ap.parse_args()
    data_dir: Path = args.data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "fleet.sqlite"
    token = str(os.environ.get("FLEET_BEARER_TOKEN") or "").strip()
    force_bearer = str(os.environ.get("FLEET_ENFORCE_BEARER") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    loopback_only = _loopback_bind_only(args.host)
    loopback_skips_auth = bool(token) and loopback_only and not force_bearer

    conn = store.connect(db_path)
    conn.close()
    container_layout.ensure_layout(data_dir)
    if container_templates.prefetch_template_images_enabled():

        def _prefetch_templates_bg() -> None:
            container_templates.prefetch_requirement_template_images(data_dir)

        threading.Thread(
            target=_prefetch_templates_bg,
            name="fleet-template-prefetch",
            daemon=True,
        ).start()
    try:
        n_gc = workspace_bundle.gc_stale_workspaces(data_dir, db_path, max_age_seconds=86400.0 * 7)
        if n_gc:
            print(f"[fleet] workspace GC removed {n_gc} stale job-workspaces dir(s)")
    except OSError:
        pass

    httpd = ThreadingHTTPServer((args.host, args.port), FleetHandler)
    httpd.db_path = db_path
    httpd.fleet_data_dir = str(data_dir)
    httpd.listen_host = str(args.host)
    httpd.expected_token = token
    httpd.loopback_bind_skips_auth = loopback_skips_auth
    httpd.fleet_started_epoch = time.time()
    httpd.fleet_started_utc = datetime.now(UTC).isoformat()
    if loopback_skips_auth:
        auth_note = "off (loopback bind — bearer not required; set FLEET_ENFORCE_BEARER=1 to force)"
    elif token:
        auth_note = "bearer"
    else:
        auth_note = "disabled (no FLEET_BEARER_TOKEN)"
    print(f"[fleet] http://{args.host}:{args.port}/  db={db_path} auth={auth_note}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
