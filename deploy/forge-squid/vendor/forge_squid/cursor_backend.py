"""Cursor Composer as an OpenAI-shaped chat backend.

Selected when ``FORGE_SQUID_BACKEND_MODEL_ID`` is ``composer`` or ``composer-*``,
or when ``FORGE_SQUID_BACKEND_KIND=cursor``. The call is one plan-mode agent
prompt in an empty directory. It does not replace the forge-llm gateway path.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

DEFAULT_COMPOSER = "composer-2.5"
_CWD = Path(os.environ.get("FORGE_SQUID_CURSOR_CWD", "/tmp/forge-2b-cursor"))


class CursorBackendError(RuntimeError):
    pass


def is_cursor_model(model: str) -> bool:
    name = model.strip().lower()
    return name == "composer" or name.startswith("composer-")


def resolve_kind(model: str) -> str:
    explicit = os.environ.get("FORGE_SQUID_BACKEND_KIND", "").strip().lower()
    if explicit in {"gateway", "cursor"}:
        return explicit
    return "cursor" if is_cursor_model(model) else "gateway"


def api_key() -> str:
    return (os.environ.get("FORGE_SQUID_CURSOR_API_KEY") or os.environ.get("CURSOR_API_KEY") or "").strip()


def sdk_model_id(model: str) -> str:
    name = model.strip()
    if name.lower() == "composer":
        return DEFAULT_COMPOSER
    return name


def render_prompt(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = [
        "You are the completion backend for forge-squid. Reply with only the assistant message. "
        "Do not use tools. Do not edit files. Do not add a preamble or a status line."
    ]
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user")
        content = message.get("content")
        if isinstance(content, list):
            content = "\n".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        text = content if isinstance(content, str) else ""
        if text.strip():
            parts.append(f"{role}:\n{text}")
    return "\n\n".join(parts)


def _prompt(prompt: str, model: str, key: str) -> Any:
    from cursor_sdk import Agent, AgentOptions, LocalAgentOptions, SandboxOptions

    _CWD.mkdir(parents=True, exist_ok=True)
    return Agent.prompt(
        prompt,
        AgentOptions(
            api_key=key,
            model=model,
            mode="plan",
            local=LocalAgentOptions(
                cwd=str(_CWD),
                setting_sources=[],
                sandbox_options=SandboxOptions(enabled=True),
            ),
        ),
    )


def complete(messages: list[dict[str, Any]], model: str) -> dict[str, Any]:
    key = api_key()
    if not key:
        raise CursorBackendError("missing cursor api key")
    result = _prompt(render_prompt(messages), sdk_model_id(model), key)
    status = getattr(result, "status", None)
    if status != "finished":
        raise CursorBackendError(f"cursor run status {status}")
    text = str(getattr(result, "result", None) or "").strip()
    if not text:
        raise CursorBackendError("empty cursor result")
    return {
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
    }
