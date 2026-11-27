"""Cursor Plan and Agent turns sent through the OpenAI chat-completions shim.

Cursor Plan mode posts the conversation, a system prompt, and a tools array.
Ordinary forge-squid chat rejects that body. This module builds the payload
the forge-llm gateway can accept, and leaves comprehension chat unchanged.
"""

from __future__ import annotations

from typing import Any

_COPY_FIELDS = (
    "temperature",
    "top_p",
    "max_tokens",
    "max_completion_tokens",
    "stop",
    "parallel_tool_calls",
    "user",
)


def is_tool_turn(body: dict[str, Any]) -> bool:
    """True when Cursor is driving Plan or Agent with tools, not plain chat."""
    tools = body.get("tools")
    if isinstance(tools, list) and tools:
        return True
    choice = body.get("tool_choice")
    if choice not in (None, "none"):
        return True
    messages = body.get("messages")
    if not isinstance(messages, list):
        return False
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("role") == "tool" or message.get("tool_calls"):
            return True
    return False


def sanitize_tools(tools: Any) -> list[dict[str, Any]]:
    """Keep OpenAI function tools. Drop Cursor-only tool entries the gateway rejects."""
    if not isinstance(tools, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        function = tool.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        kept: dict[str, Any] = {"name": name}
        description = function.get("description")
        if isinstance(description, str):
            kept["description"] = description
        parameters = function.get("parameters")
        if isinstance(parameters, dict):
            kept["parameters"] = parameters
        cleaned.append({"type": "function", "function": kept})
    return cleaned


def _tool_choice(choice: Any, tools: list[dict[str, Any]]) -> Any | None:
    names = {tool["function"]["name"] for tool in tools}
    if choice in ("auto", "none", "required"):
        return choice
    if isinstance(choice, dict):
        function = choice.get("function")
        name = function.get("name") if isinstance(function, dict) else None
        if isinstance(name, str) and name in names:
            return {"type": "function", "function": {"name": name}}
    return "auto"


def passthrough_payload(body: dict[str, Any], upstream: str) -> dict[str, Any]:
    """Gateway body: original messages, sanitized tools, caller stream flag."""
    payload: dict[str, Any] = {
        "model": upstream,
        "messages": body.get("messages") if isinstance(body.get("messages"), list) else [],
        "stream": body.get("stream") is True,
    }
    tools = sanitize_tools(body.get("tools"))
    if tools:
        payload["tools"] = tools
        choice = _tool_choice(body.get("tool_choice"), tools)
        if choice is not None:
            payload["tool_choice"] = choice
    for key in _COPY_FIELDS:
        if key in body and body[key] is not None:
            payload[key] = body[key]
    return payload
