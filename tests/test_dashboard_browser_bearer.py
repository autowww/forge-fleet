from pathlib import Path

from fleet_server import dashboard_browser_bearer


def test_write_read_bearer(tmp_path: Path) -> None:
    dashboard_browser_bearer.write_bearer(tmp_path, "secret-token")
    assert dashboard_browser_bearer.configured(tmp_path)
    assert dashboard_browser_bearer.read_bearer(tmp_path) == "secret-token"
    dashboard_browser_bearer.clear_bearer(tmp_path)
    assert not dashboard_browser_bearer.configured(tmp_path)
