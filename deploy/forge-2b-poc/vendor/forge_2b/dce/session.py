"""Conversation identity and follow-up resolution for the DCE lane (decision 5, 2026-11-06).

Open WebUI with ``ENABLE_FORWARD_USER_INFO_HEADERS=true`` (upstream core feature, set in forge-fleet
``deploy/open-webui/compose.yaml``) sends ``X-OpenWebUI-Chat-Id`` and ``X-OpenWebUI-User-{Id,Name,Email,Role}`` on every
chat completion. The shim keys follow-up turns by the chat id, falls back to ``X-Forge-Chat-Id`` for direct API callers and
then to a hash of the prior assistant turns (the OpenAI-style history itself), and keeps **only a hash** of the user id —
never the name or the email. The per-key store holds the last two turns (question, how it was read, the pointers it rested
on) with a TTL; nothing is written to disk.

Follow-up resolution is deterministic text work: an elliptical question ("And in the public re-run?", "Which commit
introduced it?") is rewritten with the previous turn's scope or object noun phrase, and the rewrite is shown to the user
("read as …, from your previous question") so nothing is resolved silently. When the shape is not recognised the question
is left as it is and answered on its own.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Mapping

HEADER_CHAT_ID = "x-openwebui-chat-id"
HEADER_FORGE_CHAT_ID = "x-forge-chat-id"
# Open WebUI's placeholder chat ids for API calls that belong to no chat (`local`) or serialised absent values: never a
# session key — every API caller would otherwise share one conversation
_PLACEHOLDER_IDS = frozenset({"local", "none", "null", "undefined"})
HEADER_USER_ID = "x-openwebui-user-id"


def _h(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def user_ref(headers: Mapping[str, str]) -> str | None:
    """A stable, non-reversible reference to the Open WebUI user — the only thing about the user the shim ever records."""
    uid = (headers.get(HEADER_USER_ID) or "").strip()
    return _h("owui-user:" + uid) if uid else None


def conversation_key(headers: Mapping[str, str], messages: list[dict[str, Any]] | None) -> tuple[str | None, str]:
    """``(key, source)``: the Open WebUI chat id → an explicit ``X-Forge-Chat-Id`` → a hash of the prior assistant turns in
    the request history → ``(None, "none")`` for a first turn with no history (no session is created for it)."""
    cid = (headers.get(HEADER_CHAT_ID) or "").strip()
    if cid and cid.lower() not in _PLACEHOLDER_IDS:
        return _h("owui-chat:" + cid), "openwebui_chat_id"
    fid = (headers.get(HEADER_FORGE_CHAT_ID) or "").strip()
    if fid:
        return _h("forge-chat:" + fid), "forge_chat_id"
    prior = [str(m.get("content") or "") for m in (messages or []) if isinstance(m, dict) and m.get("role") == "assistant"]
    if prior:
        return _h("history:" + "\n".join(prior)), "history_hash"
    return None, "none"


@dataclass
class Turn:
    question: str                                 # as asked (after any follow-up rewrite: what the engine actually read)
    asked: str                                    # the user's literal text of that turn
    goals: list[dict[str, Any]] = field(default_factory=list)   # sanitized: {kind, operator, status, method, spans[path:line]}
    answer_head: str = ""                         # first 300 chars of the stated answer (no evidence), for "it" = the answer value
    at: float = field(default_factory=time.time)


class SessionStore:
    """In-memory, per conversation key, last ``depth`` turns, ``ttl_s`` seconds. Thread-safe; bounded by ``max_keys``."""

    def __init__(self, *, depth: int = 2, ttl_s: float = 1800.0, max_keys: int = 500) -> None:
        self.depth, self.ttl_s, self.max_keys = depth, ttl_s, max_keys
        self._d: OrderedDict[str, list[Turn]] = OrderedDict()
        self._lock = threading.Lock()

    def _sweep(self, now: float) -> None:
        dead = [k for k, turns in self._d.items() if not turns or now - turns[-1].at > self.ttl_s]
        for k in dead:
            self._d.pop(k, None)
        while len(self._d) > self.max_keys:
            self._d.popitem(last=False)

    def last(self, key: str | None) -> Turn | None:
        if not key:
            return None
        with self._lock:
            self._sweep(time.time())
            turns = self._d.get(key)
            if turns:
                self._d.move_to_end(key)
                return turns[-1]
            return None

    def push(self, key: str | None, turn: Turn) -> None:
        if not key:
            return
        with self._lock:
            self._sweep(time.time())
            turns = self._d.setdefault(key, [])
            turns.append(turn)
            del turns[:-self.depth]
            self._d.move_to_end(key)
            while len(self._d) > self.max_keys:
                self._d.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._d)


# --- follow-up resolution --------------------------------------------------------------------------------------------------
_ELLIPTICAL_SCOPE_RE = re.compile(r"^\s*(?:and|what about|how about|also)?\s*(?:(?:in|for|on|at|under|during|with|within)\s+)(?P<scope>.+?)\s*\??\s*$", re.I)
_PREV_SCOPE_RE = re.compile(r"\b(?P<prep>in|for|on|at|under|during|with|within)\s+(?P<scope>(?:the|a|an|this|that)\s+[^?]+?)\s*\??\s*$", re.I)
_PRONOUN_RE = re.compile(r"\b(it|this|that|its|them|they|those|these)\b", re.I)
_WH_LEAD_RE = re.compile(r"^\s*(?:what|which|who|whom|when|where|why|how(?:\s+many|\s+much)?)\b\s*(?:\w+\s+){0,3}?(?:is|are|was|were|did|does|do|has|have|had)\b\s*", re.I)
_OBJECT_NP_RE = re.compile(r"\b(?:did|does|do|has|have|had|was|were|is|are)\s+(?P<np>(?:the|a|an|this|that)\s+.+?)\s+\w+\s*\??\s*$", re.I)
_OF_NP_RE = re.compile(r"\b(?:of|for|in)\s+(?P<np>(?:the|a|an|this|that)\s+[^?]+?)\s*\??\s*$", re.I)
_NOUNISH_RE = re.compile(r"[A-Za-z][\w.-]{3,}")
_WH_WORD_RE = re.compile(r"what|which|whom|when|where|why|many|much|does|did|have|has|the|and|that|this", re.I)


@dataclass(frozen=True)
class FollowUp:
    rewritten: str        # the question the engine reads
    kind: str             # scope_substitution | pronoun_antecedent
    note: str             # shown to the user: how the question was read and from which previous turn


def _object_np(prev_question: str) -> str | None:
    """The noun phrase the previous question was about: "Which parser version did **the post-blind safety increment** ship?"
    → that phrase; "What is the verdict of **this increment**?" → "this increment"; else the question minus its wh-lead."""
    m = _OF_NP_RE.search(prev_question)       # trailing "of/for/in the X" first: "the verdict of this increment" → "this increment"
    if m:
        return m.group("np").strip()
    m = _OBJECT_NP_RE.search(prev_question)
    if m:
        return m.group("np").strip()
    rest = _WH_LEAD_RE.sub("", prev_question).strip().rstrip("?").strip()
    return rest or None


def resolve_follow_up(question: str, prev: Turn | None) -> FollowUp | None:
    """Rewrite an elliptical or pronoun-only question with the previous turn; ``None`` when the question stands alone
    (it has its own content nouns and no dangling pronoun, or no previous turn exists)."""
    if prev is None:
        return None
    q = question.strip()
    # 1. "And in the public re-run?" — a bare scope: swap it into the previous question's scope ("… in the blind run")
    m = _ELLIPTICAL_SCOPE_RE.match(q)
    if m and len(_NOUNISH_RE.findall(m.group("scope"))) <= 4 and not re.search(r"\b(is|are|was|were|did|does|do|has|have)\b", q, re.I):
        pm = _PREV_SCOPE_RE.search(prev.question)
        if pm:
            new_q = prev.question[: pm.start("scope")] + m.group("scope").strip() + "?"
            return FollowUp(new_q, "scope_substitution",
                            f"read as “{new_q}” — the scope “{m.group('scope').strip()}” replaces “{pm.group('scope').strip()}” from your previous question")
        return None
    # 2. "Which commit introduced it?" — a pronoun with no antecedent noun in the question itself
    nouns = [w for w in _NOUNISH_RE.findall(_WH_LEAD_RE.sub("", q)) if not _PRONOUN_RE.fullmatch(w) and not _WH_WORD_RE.fullmatch(w)]
    pm2 = _PRONOUN_RE.search(q)
    if pm2 and len(nouns) <= 2:
        np_ = _object_np(prev.question)
        if np_:
            pron = pm2.group(1)
            repl = np_ if pron.lower() not in ("its",) else np_ + "'s"
            new_q = q[: pm2.start()] + repl + q[pm2.end():]
            return FollowUp(new_q, "pronoun_antecedent",
                            f"read as “{new_q}” — “{pron}” taken as “{np_}” from your previous question")
    return None


def turn_from_results(asked: str, question: str, results: list[dict[str, Any]], answer_head: str) -> Turn:
    """Build the stored turn from the sanitized per-node trace (``results_trace`` rows): no file text, only pointers."""
    goals = [{"kind": r.get("kind"), "status": r.get("status"), "method": r.get("method"), "spans": list(r.get("spans") or [])[:4]}
             for r in results if str(r.get("node_id", "")).startswith("g")]
    return Turn(question=question, asked=asked, goals=goals, answer_head=(answer_head or "")[:300])
