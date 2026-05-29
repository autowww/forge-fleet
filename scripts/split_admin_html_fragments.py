#!/usr/bin/env python3
"""One-shot: split fleet_server/static/admin.html into html-src fragments."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ADMIN_HTML = REPO / "fleet_server" / "static" / "admin.html"
HTML_SRC = REPO / "fleet_server" / "static" / "admin" / "html_src"

# (manifest path, 1-based inclusive line range in admin.html)
SLICES: list[tuple[str, int, int]] = [
    ("shell/document-start.html", 1, 29),
    ("chrome/theme-dropdown.html", 30, 69),
    ("chrome/a11y-overview-trigger.html", 71, 83),
    ("main/header.html", 85, 103),
    ("main/tab-nav.html", 105, 165),
    ("main/tab-content-open.html", 167, 167),
    ("tabs/overview-pane.html", 168, 208),
    ("tabs/services-pane.html", 210, 263),
    ("tabs/containers-pane.html", 265, 305),
    ("tabs/jobs-pane.html", 307, 352),
    ("main/main-close.html", 353, 353),
    ("modals/job-detail.html", 355, 373),
    ("modals/type-edit.html", 375, 430),
    ("modals/req-template.html", 432, 477),
    ("modals/system-update.html", 479, 507),
    ("modals/power-diag.html", 509, 544),
    ("modals/tel-history.html", 546, 587),
    ("modals/a11y-overview.html", 589, 642),
    ("shell/scripts.html", 644, 673),
    ("shell/document-end.html", 674, 675),
]

MANIFEST = """# Admin HTML shell — assembly order for /admin/ (see html_src/README.md).
shell/document-start.html
chrome/theme-dropdown.html
chrome/a11y-overview-trigger.html
main/header.html
main/tab-nav.html
main/tab-content-open.html
tabs/overview-pane.html
tabs/services-pane.html
tabs/containers-pane.html
tabs/jobs-pane.html
main/main-close.html
modals/job-detail.html
modals/type-edit.html
modals/req-template.html
modals/system-update.html
modals/power-diag.html
modals/tel-history.html
modals/a11y-overview.html
shell/scripts.html
shell/document-end.html
"""


def main() -> None:
    lines = ADMIN_HTML.read_text(encoding="utf-8").splitlines(keepends=True)
    HTML_SRC.mkdir(parents=True, exist_ok=True)
    for rel, start, end in SLICES:
        out = HTML_SRC / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("".join(lines[start - 1 : end]), encoding="utf-8")
    (HTML_SRC / "MANIFEST.txt").write_text(MANIFEST, encoding="utf-8")
    print(f"split admin.html -> {len(SLICES)} fragments under html_src/")


if __name__ == "__main__":
    main()
