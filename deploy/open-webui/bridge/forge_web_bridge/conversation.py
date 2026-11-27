"""Decide whether an API request continues the open web chat."""

from __future__ import annotations

from typing import Any


def _text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "\n".join(parts).strip()
    return ""


def continues_conversation(messages: list[dict[str, Any]]) -> bool:
    """True when the caller sent an earlier turn, so the open chat should stay."""
    users = 0
    assistants = 0
    for message in messages:
        if not isinstance(message, dict) or not _text(message):
            continue
        role = str(message.get("role") or "")
        if role == "user":
            users += 1
        elif role == "assistant":
            assistants += 1
    return users > 1 or assistants > 0


def follow_up_prompt(messages: list[dict[str, Any]]) -> str:
    """Pack earlier turns into the new user text when the web UI opens a fresh chat."""
    last_user_at: int | None = None
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, dict) and message.get("role") == "user" and _text(message):
            last_user_at = index
            break
    if last_user_at is None:
        return ""
    prior: list[str] = []
    for message in messages[:last_user_at]:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "")
        text = _text(message)
        if role in ("user", "assistant") and text:
            prior.append(f"{role}: {text}")
    latest = _text(messages[last_user_at])
    if not prior:
        return latest
    return "Continue this conversation.\n\n" + "\n\n".join(prior) + "\n\nuser: " + latest
