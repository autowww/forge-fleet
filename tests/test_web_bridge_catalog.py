from forge_web_bridge.catalog import (
    catalog_row_for_slug,
    openai_models_payload,
    variant_model_id,
)


def test_variant_model_id() -> None:
    assert variant_model_id("granite-chatgpt-primary", "gpt-4o") == "granite-chatgpt-primary.gpt-4o"


def test_openai_models_payload_includes_base_and_variants() -> None:
    body = openai_models_payload("chatgpt", "granite-chatgpt-primary", live_labels=None)
    ids = [row["id"] for row in body["data"]]
    assert "granite-chatgpt-primary" in ids
    assert "granite-chatgpt-primary.gpt-4o" in ids


def test_catalog_row_for_slug() -> None:
    row = catalog_row_for_slug("gemini", "fast")
    assert row is not None
    assert row.get("label") == "Fast"
