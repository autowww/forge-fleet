"""Strip forge-squid live-graph chrome from text stored in chat history or session memory."""
from __future__ import annotations

import re
from contextvars import ContextVar
from typing import Any

from . import env_keys

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


_EXP: ContextVar[dict[str, Any] | None] = ContextVar("forge_squid_chat_exp", default=None)


def set_chat_experiment(flags: dict[str, Any] | None):
    """Per-request experiment overrides (from X-Forge-Squid-Exp-* headers)."""
    return _EXP.set(flags)


def reset_chat_experiment(token) -> None:
    _EXP.reset(token)


def _env_flag(suffix: str, *, default: str = "1") -> bool:
    return env_keys.squid_env(suffix, default).strip().lower() in ("1", "true", "yes", "on")


def _exp_flag(key: str, env_suffix: str) -> bool:
    exp = _EXP.get()
    if exp is not None and key in exp:
        val = exp[key]
        if val is None or val == "":
            return _env_flag(env_suffix)
        return str(val).strip().lower() in ("1", "true", "yes", "on")
    return _env_flag(env_suffix)


def sanitize_chat_history() -> bool:
    return _exp_flag("sanitize", "CHAT_SANITIZE_HISTORY")


def chat_prose_only() -> bool:
    return _exp_flag("prose_only", "CHAT_PROSE_ONLY")


def chat_continue_on_length() -> bool:
    return _exp_flag("continue", "CHAT_CONTINUE_ON_LENGTH")


def chat_stream_graph() -> bool:
    """When true (default), streamed chat answers include live ```html graph snapshots in the body."""
    return _exp_flag("stream_graph", "CHAT_STREAM_GRAPH")


def env_contract_note_mode() -> str:
    """off | mechanical (default) | full — full restores pre-remediation answer-key notes."""
    mode = env_keys.squid_env("CONTRACT_NOTE", "mechanical").strip().lower()
    if mode in ("off", "0", "false", "no"):
        return "off"
    if mode == "full":
        return "full"
    return "mechanical"
