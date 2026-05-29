#!/usr/bin/env python3
"""Regenerate fleet_server/static/admin.html from html_src fragments (optional deploy bundle)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HTML_SRC = REPO / "fleet_server" / "static" / "admin" / "html_src"
OUT = REPO / "fleet_server" / "static" / "admin.html"

sys.path.insert(0, str(REPO))

from fleet_server.admin_shell import assemble_admin_html  # noqa: E402


def main() -> None:
    html = assemble_admin_html(html_src=HTML_SRC)
    OUT.write_text(html, encoding="utf-8")
    print(f"bundle_admin_html: wrote {OUT} ({len(html.splitlines())} lines)")


if __name__ == "__main__":
    main()
