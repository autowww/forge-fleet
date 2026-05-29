"""Admin HTML shell assembly from html_src fragments."""

from __future__ import annotations

from pathlib import Path

from fleet_server.admin_shell import assemble_admin_html

_HTML_SRC = Path(__file__).resolve().parents[1] / "fleet_server" / "static" / "admin" / "html_src"


def test_assemble_admin_html_includes_core_regions() -> None:
    html = assemble_admin_html(html_src=_HTML_SRC)
    assert "<main class=\"container pb-5\">" in html
    assert 'id="fleet-tab-overview"' in html
    assert 'id="fleet-tab-jobs"' in html
    assert 'id="fleet-a11y-overview-modal"' in html
    assert 'id="fleet-load-chart"' in html
    assert html.strip().endswith("</html>")


def test_assemble_admin_html_matches_manifest_file_count() -> None:
    manifest = (_HTML_SRC / "MANIFEST.txt").read_text(encoding="utf-8")
    names = [ln.strip() for ln in manifest.splitlines() if ln.strip() and not ln.startswith("#")]
    assert len(names) == 20
    for name in names:
        assert (_HTML_SRC / name).is_file(), name


def test_assemble_admin_html_has_balanced_main_and_tab_content() -> None:
    html = assemble_admin_html(html_src=_HTML_SRC)
    assert html.count("<main") == 1
    assert html.count("</main>") == 1
    assert html.count('id="fleet-admin-tab-content"') == 1
    assert html.count('class="tab-pane') == 4
