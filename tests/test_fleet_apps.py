"""Tests for FAEP v1 fleet_apps module."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from fleet_server import fleet_apps


def _minimal_zip(
    *,
    app_id: str = "test-app",
    version: str = "0.0.1",
    with_handlers: bool = True,
) -> bytes:
  buf = io.BytesIO()
  manifest = {
      "protocol_version": 1,
      "id": app_id,
      "version": version,
      "title": "Test App",
      "summary": "Test",
      "python": {"package": "test_pkg", "handlers_module": "test_pkg.handlers"},
      "ui": {"spec": "ui/app.ui.json"},
      "docs": {"root": "docs"},
      "permissions": [],
  }
  ui = {"protocol_version": 1, "widgets": [{"kind": "prose", "text": "Hello"}]}
  handlers = '''
def register_handlers():
    return {
        "data": {"ping": lambda ctx: {"ok": True, "value": "pong"}},
        "actions": {"noop": lambda ctx, body: {"ok": True}},
    }
'''
  with zipfile.ZipFile(buf, "w") as zf:
      zf.writestr("fleet-app.manifest.json", json.dumps(manifest))
      zf.writestr("ui/app.ui.json", json.dumps(ui))
      zf.writestr("docs/README.md", "# Test docs\n")
      if with_handlers:
          zf.writestr("src/test_pkg/__init__.py", "")
          zf.writestr("src/test_pkg/handlers.py", handlers)
          zf.writestr("pyproject.toml", '[project]\nname="test_pkg"\nversion="0.0.1"\n')
  return buf.getvalue()


def test_install_and_ui_spec(tmp_path: Path) -> None:
    data = _minimal_zip()
    rec = fleet_apps.install_package_bytes(tmp_path, data)
    assert rec["id"] == "test-app"
    spec = fleet_apps.get_ui_spec(tmp_path, "test-app")
    assert spec["protocol_version"] == 1
    installed = fleet_apps.list_installed(tmp_path)
    assert len(installed) == 1
    snap = fleet_apps.snapshot_apps(tmp_path)
    assert snap[0]["id"] == "test-app"


def test_uninstall(tmp_path: Path) -> None:
    data = _minimal_zip()
    fleet_apps.install_package_bytes(tmp_path, data)
    fleet_apps.uninstall(tmp_path, "test-app")
    assert fleet_apps.load_installed_record(tmp_path, "test-app") is None


def test_render_doc_html(tmp_path: Path) -> None:
    data = _minimal_zip()
    fleet_apps.install_package_bytes(tmp_path, data)
    html = fleet_apps.render_doc_html(tmp_path, "test-app", "index")
    assert html is not None
    assert "Test docs" in html


def test_compare_versions() -> None:
    assert fleet_apps.compare_versions("0.2.0", "0.1.0") > 0
    assert fleet_apps.compare_versions("0.1.0", "0.2.0") < 0
    assert fleet_apps.compare_versions("1.0.0", "1.0.0") == 0
    assert fleet_apps.version_gt("0.2.1", "0.2.0")


def test_runtime_config_roundtrip(tmp_path: Path) -> None:
    fleet_apps.write_app_runtime_config(tmp_path, "forge-cdp-manager", {"manager_enabled": True})
    doc = fleet_apps.read_app_runtime_config(tmp_path, "forge-cdp-manager")
    assert doc["manager_enabled"] is True


def test_upgrade_replaces_old_install_dir(tmp_path: Path) -> None:
    v1 = _minimal_zip(version="0.1.0")
    v2 = _minimal_zip(version="0.2.0")
    fleet_apps.install_package_bytes(tmp_path, v1)
    first = fleet_apps.load_installed_record(tmp_path, "test-app")
    assert first is not None
    old_path = Path(str(first["install_path"]))
    assert old_path.is_dir()
    fleet_apps.install_package_bytes(tmp_path, v2)
    second = fleet_apps.load_installed_record(tmp_path, "test-app")
    assert second is not None
    assert second["app_version"] == "0.2.0"
    assert not old_path.exists()


def test_sha256_mismatch(tmp_path: Path) -> None:
    data = _minimal_zip()
    with pytest.raises(ValueError, match="sha256_mismatch"):
        fleet_apps.install_package_bytes(tmp_path, data, expected_sha256="0" * 64)


def test_proxy_surface_snapshot_not_installed(tmp_path: Path) -> None:
    code, body, ctype, _headers = fleet_apps.proxy_surface_snapshot(
        tmp_path,
        "forge-cdp-manager",
        "outlook_mail",
        "http://127.0.0.1:9222",
    )
    assert code == 404
    assert b"not installed" in body.lower()


def test_proxy_surface_snapshot_upstream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = _minimal_zip(app_id="forge-cdp-manager")
    fleet_apps.install_package_bytes(tmp_path, data)
    fleet_apps.write_app_runtime_config(
        tmp_path,
        "forge-cdp-manager",
        {"daemon_url": "http://127.0.0.1:18770"},
    )
    fake_jpeg = b"\xff\xd8\xff\xd9"

    class _FakeResp:
        headers = {"Content-Type": "image/jpeg", "Cache-Control": "max-age=55, private"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return fake_jpeg

    def _fake_urlopen(req, timeout=30.0):
        assert "snapshot.jpg" in req.full_url
        assert "outlook_mail" in req.full_url
        return _FakeResp()

    monkeypatch.setattr("fleet_server.fleet_apps.urllib.request.urlopen", _fake_urlopen)
    code, body, ctype, headers = fleet_apps.proxy_surface_snapshot(
        tmp_path,
        "forge-cdp-manager",
        "outlook_mail",
        "http://127.0.0.1:9222",
    )
    assert code == 200
    assert body == fake_jpeg
    assert ctype == "image/jpeg"
    assert "max-age=55" in headers.get("Cache-Control", "")

