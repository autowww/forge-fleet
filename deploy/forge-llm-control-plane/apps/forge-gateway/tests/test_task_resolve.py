from __future__ import annotations

import pytest

from control_plane.task_resolve import (
    MODE_TO_TASK,
    resolve_task,
    assert_task_supported,
)


def test_explicit_forge_task_beats_rules():
    res = resolve_task(
        header_task=None,
        body_task="finance_facts",
        header_mode=None,
        body_mode=None,
        path="/v1/chat/completions",
        body={"messages": [{"role": "user", "content": "def foo(): pass"}]},
    )
    assert res.task_id == "finance_facts"
    assert res.source == "body_task"


def test_header_task_wins():
    res = resolve_task(
        header_task="code_review",
        body_task="chat",
        header_mode=None,
        body_mode=None,
        path="/v1/chat/completions",
        body={},
    )
    assert res.task_id == "code_review"


def test_unknown_task_raises():
    with pytest.raises(ValueError, match="unknown task"):
        resolve_task(
            header_task="not_a_real_task",
            body_task=None,
            header_mode=None,
            body_mode=None,
            path="/v1/chat/completions",
            body={},
        )


def test_embeddings_path():
    res = resolve_task(
        header_task=None,
        body_task=None,
        header_mode=None,
        body_mode=None,
        path="/v1/embeddings",
        body={},
    )
    assert res.task_id == "embedding"
    assert res.mode == "embed"


def test_unsupported_media_task():
    with pytest.raises(ValueError, match="dedicated pipeline"):
        assert_task_supported("asr")


def test_mode_maps_to_task():
    assert MODE_TO_TASK["task_code"] == "code_generate"
