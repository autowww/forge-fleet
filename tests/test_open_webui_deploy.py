from pathlib import Path


def test_open_webui_compose_files_exist() -> None:
    root = Path(__file__).resolve().parents[1] / "deploy" / "open-webui"
    assert (root / "compose.yaml").is_file()
    assert (root / "compose.granite.yaml").is_file()
    text = (root / "compose.yaml").read_text(encoding="utf-8")
    assert "open-webui/open-webui:v0.12.3" in text
    assert "pgvector" in text


def test_caddy_installer_has_open_webui_site_block() -> None:
    script = (
        Path(__file__).resolve().parents[1] / "scripts" / "install-caddy-fleet-ollama-unified.sh"
    ).read_text(encoding="utf-8")
    assert "append_open_webui_site_block" in script
    assert "OPEN_WEBUI_SITE_ADDRESS" in script
    assert "flush_interval -1" in script


def test_rollout_script_exists() -> None:
    path = Path(__file__).resolve().parents[1] / "scripts" / "rollout-open-webui.sh"
    assert path.is_file()
