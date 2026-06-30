"""Admin dashboard HTML/JS smoke guards."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ADMIN = Path(__file__).resolve().parents[1] / "fleet_server" / "static" / "admin.html"


def test_admin_inline_script_syntax() -> None:
    html = ADMIN.read_text(encoding="utf-8")
    scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
    assert len(scripts) >= 3
    main = scripts[2]
    path = Path("/tmp/fleet-admin-main.js")
    path.write_text(main, encoding="utf-8")
    subprocess.run(["node", "--check", str(path)], check=True, capture_output=True, text=True)


def test_admin_no_fleet_app_tab_quote_regression() -> None:
    html = ADMIN.read_text(encoding="utf-8")
    assert '"></div></div>"' not in html
    assert "REMOTE_GIT_POLL_MS" in html


def test_smoke_script_exists() -> None:
    smoke = Path(__file__).resolve().parents[1] / "scripts" / "smoke-admin-ui.mjs"
    assert smoke.is_file()
