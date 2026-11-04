from pathlib import Path

import subprocess


def test_open_webui_host_guard_script_exists() -> None:
    path = Path(__file__).resolve().parents[1] / "deploy" / "open-webui" / "scripts" / "open-webui-host-guard.sh"
    assert path.is_file()


def test_open_webui_host_guard_rejects_without_granite_role() -> None:
    guard = Path(__file__).resolve().parents[1] / "deploy" / "open-webui" / "scripts" / "open-webui-host-guard.sh"
    env = {"FORGE_HOST_ROLE": "", "FORGE_OPEN_WEBUI_FORCE_LOCAL": "", "HOME": "/tmp"}
    proc = subprocess.run(["bash", str(guard)], env=env, capture_output=True, text=True, check=False)
    assert proc.returncode == 1
    assert "Granite-only" in proc.stderr


def test_open_webui_host_guard_allows_granite_role() -> None:
    guard = Path(__file__).resolve().parents[1] / "deploy" / "open-webui" / "scripts" / "open-webui-host-guard.sh"
    env = {"FORGE_HOST_ROLE": "granite", "HOME": "/tmp"}
    proc = subprocess.run(["bash", str(guard)], env=env, capture_output=True, text=True, check=False)
    assert proc.returncode == 0
    root = Path(__file__).resolve().parents[1] / "deploy" / "open-webui"
    assert (root / "compose.yaml").is_file()
    assert (root / "compose.granite.yaml").is_file()
    text = (root / "compose.yaml").read_text(encoding="utf-8")
    assert "open-webui/open-webui:v0.13.0" in text
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
