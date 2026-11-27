from forge_web_bridge.catalog import (
    catalog_row_for_slug,
    openai_models_payload,
    resolve_requested_model,
    variant_model_id,
)


def test_variant_model_id() -> None:
    assert variant_model_id("granite-chatgpt-primary", "gpt-4o") == "granite-chatgpt-primary.gpt-4o"


def test_openai_models_payload_announces_saved_aliases_with_burn_credits() -> None:
    body = openai_models_payload("chatgpt", "granite-chatgpt-primary", live_labels=None)
    ids = [row["id"] for row in body["data"]]
    assert "granite-chatgpt-primary" not in ids
    assert "chatgpt-4o" not in ids
    assert "chatgpt-6-astra-max" in ids
    assert "chatgpt-6-sol-instant" in ids
    by_id = {row["id"]: row for row in body["data"]}
    astra = by_id["chatgpt-6-astra-max"]["credits_per_1000000_tokens"]
    assert astra["output"] == 11375
    assert astra["burn_rank"] == 1
    assert by_id["chatgpt-6-sol-instant"]["credits_per_1000000_tokens"]["output"] == 167.5
    assert by_id["chatgpt-6-sol-light"]["credits_per_1000000_tokens"]["output"] == 250
    gemini = {row["id"]: row for row in openai_models_payload("gemini", "granite-gemini-primary")["data"]}
    assert gemini["gemini-fast"]["credits_per_1000000_tokens"]["output"] == 93.75
    assert gemini["gemini-neon-medium"]["credits_per_1000000_tokens"]["output"] == 206.25
    assert gemini["gemini-thinking"]["credits_per_1000000_tokens"]["output"] == 206.25
    assert gemini["gemini-pro"]["credits_per_1000000_tokens"]["output"] == 300
    assert gemini["gemini-fast"]["credits_per_1000000_tokens"]["burn_rank"] == 15


def test_short_alias_resolves_astra_max() -> None:
    choice = resolve_requested_model("chatgpt", "granite-chatgpt-primary", "chatgpt-6-astra-max")
    assert choice is not None
    assert choice["effort_kind"] == "time"
    assert choice["effort_id"] == "max"
    assert choice["label"] == "Max"


def test_follow_up_stays_one_conversation() -> None:
    from forge_web_bridge.conversation import continues_conversation, follow_up_prompt

    first = [{"role": "user", "content": "The code word is lantern."}]
    assert continues_conversation(first) is False
    second = first + [
        {"role": "assistant", "content": "OK"},
        {"role": "user", "content": "What was the code word?"},
    ]
    assert continues_conversation(second) is True
    packed = follow_up_prompt(second)
    assert "The code word is lantern." in packed
    assert "What was the code word?" in packed


def test_gemini_neon_medium_resolves_mode_and_level() -> None:
    choice = resolve_requested_model("gemini", "granite-gemini-primary", "gemini-neon-medium")
    assert choice is not None
    assert choice["label"] == "Neon"
    assert choice["match"] == ["Neon", "Medium"]


def test_gemini_fast_is_the_time_alias() -> None:
    choice = resolve_requested_model("gemini", "granite-gemini-primary", "gemini-fast")
    assert choice is not None
    assert choice["effort_kind"] == "time"
    assert choice["label"] == "Fast"


def test_catalog_row_for_slug() -> None:
    row = catalog_row_for_slug("gemini", "fast")
    assert row is not None
    assert row.get("label") == "Fast"
