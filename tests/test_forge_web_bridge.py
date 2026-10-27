from pathlib import Path


def test_bridge_main_defines_openai_routes() -> None:
    main_py = (
        Path(__file__).resolve().parents[1]
        / "deploy"
        / "open-webui"
        / "bridge"
        / "forge_web_bridge"
        / "main.py"
    )
    text = main_py.read_text(encoding="utf-8")
    assert '@app.get("/health")' in text
    assert '@app.post("/v1/chat/completions")' in text
    assert "FORGE_WEB_BRIDGE_CDP_URL" in text
