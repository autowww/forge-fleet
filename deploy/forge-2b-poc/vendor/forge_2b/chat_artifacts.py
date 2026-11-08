"""Strip forge-2b live-graph chrome from text stored in chat history or session memory."""
from __future__ import annotations

import os
import re
from contextvars import ContextVar
from typing import Any

_LIVE_TIMELINE = re.compile(r"\n\n\*\*Live timeline:\*\*[\s\S]*\Z", re.I)
_HTML_FENCE = re.compile(r"```html\s*<!doctype html>[\s\S]*?```", re.I)
_HTML_INLINE = re.compile(r"<!doctype html>[\s\S]*?</html>", re.I)


def strip_chat_artifact(text: str) -> str:
    """Remove live timeline, HTML graph snapshots, and fenced graph blocks; keep answer prose."""
    out = text or ""
    out = _LIVE_TIMELINE.sub("", out)
    while True:
        n = _HTML_FENCE.sub("", out, count=1)
        if n == out:
            break
        out = n
    while True:
        n = _HTML_INLINE.sub("", out, count=1)
        if n == out:
            break
        out = n
    return out.strip()


_EXP: ContextVar[dict[str, Any] | None] = ContextVar("forge_2b_chat_exp", default=None)


def set_chat_experiment(flags: dict[str, Any] | None):
    """Per-request experiment overrides (from X-Forge-2B-Exp-* headers)."""
    return _EXP.set(flags)


def reset_chat_experiment(token) -> None:
    _EXP.reset(token)


def _env_flag(name: str, *, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _exp_flag(key: str, env_name: str) -> bool:
    exp = _EXP.get()
    if exp is not None and key in exp:
        val = exp[key]
        if val is None or val == "":
            return _env_flag(env_name)
        return str(val).strip().lower() in ("1", "true", "yes", "on")
    return _env_flag(env_name)


def sanitize_chat_history() -> bool:
    return _exp_flag("sanitize", "FORGE_2B_CHAT_SANITIZE_HISTORY")


def chat_prose_only() -> bool:
    return _exp_flag("prose_only", "FORGE_2B_CHAT_PROSE_ONLY")


def chat_continue_on_length() -> bool:
    return _exp_flag("continue", "FORGE_2B_CHAT_CONTINUE_ON_LENGTH")


def env_contract_note_mode() -> str:
    """off | mechanical (default) | full — full restores pre-remediation answer-key notes."""
    mode = os.environ.get("FORGE_2B_CONTRACT_NOTE", "mechanical").strip().lower()
    if mode in ("off", "0", "false", "no"):
        return "off"
    if mode == "full":
        return "full"
    return "mechanical"
