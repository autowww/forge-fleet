"""Tests for environment templates and records."""

from __future__ import annotations

from pathlib import Path

from fleet_server import env_templates, environments


def test_render_dev_env_matches_committed_example():
    tpl = env_templates.get_template("forge_market_studio")
    assert tpl is not None
    repo_root = Path(__file__).resolve().parents[1]
    source_env = repo_root / "deploy" / "forge-market-studio" / ".env.example"
    expected_path = repo_root / "deploy" / "forge-market-studio-dev" / ".env.example"
    expected = expected_path.read_text(encoding="utf-8")
    ports = env_templates.default_ports_for_env(tpl, "dev")
    rendered = env_templates.render_env(
        tpl,
        app_id="forge-market-studio",
        env_id="dev",
        ports=ports,
        source_env_path=source_env,
    )
    def _kv_lines(text: str) -> list[str]:
        return sorted(
            ln.strip()
            for ln in text.splitlines()
            if ln.strip() and "=" in ln and not ln.strip().startswith("#")
        )

    assert _kv_lines(rendered) == _kv_lines(expected)


def test_adopt_market_studio_environments(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    adopted = environments.adopt_existing(tmp_path, repo_root)
    ids = {a["id"] for a in adopted}
    assert "forge-market-studio--prod" in ids or environments.read_record(tmp_path, "forge-market-studio--prod")
    assert "forge-market-studio--dev" in ids or environments.read_record(tmp_path, "forge-market-studio--dev")
    dev = environments.read_record(tmp_path, "forge-market-studio--dev")
    if dev:
        assert dev.get("gateway_slug") == "market-studio-dev"
        assert dev.get("adopted") is True


def test_list_templates():
    tpls = env_templates.list_templates(app_id="forge-market-studio")
    assert any(t["id"] == "forge_market_studio" for t in tpls)


def test_allocate_ports_skips_in_use(monkeypatch):
    tpl = env_templates.get_template("forge_market_studio")
    assert tpl is not None

    def _not_free(port: int) -> bool:
        return port != 19793

    monkeypatch.setattr(environments, "_loopback_port_free", _not_free)
    ports = environments.allocate_ports(tpl, "dev", used=set())
    assert ports["app"] != 19793
