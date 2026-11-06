"""Conversation lane for a turn that is not an attachment, a 10-K directive, or the SOURCE fixture.

The request readers classify the latest user message. A side-effect ask with no explanatory
objective is answered from that classification and the model is not called. Every other turn
is one reply from the pinned model, with the classification passed in as a reader note.
Nothing here executes a command, writes a file, or fetches a filing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .dce.parse import parse_request as parse_dce
from .request_ir import parse_request, project_effects

SIDE_EFFECTS = ("artifact_write", "environment_mutation", "command_execution")
_IDENTITY_RE = re.compile(
    r"(?i)(?:who are you|what are you)(?!\s+[a-z])|what(?:'|’)?s your name|what is your name|"
    r"identify yourself|introduce yourself|хто ти|хто ви|що ти таке"
)
_SELF_CLAIM_RE = re.compile(
    r"(?i)\b(?:i(?:'|’)?m|i am)\s+(?:chatgpt|an ai assistant developed by openai)\b|\bi was developed by openai\b"
)
IDENTITY_TEXT = (
    "I am Forge 2B. I answer ordinary questions in this chat, I answer from a ZIP or text file you attach, "
    "and I extract statements from a 10-K when you include 10-K and an uppercase ticker such as NVDA. "
    "I am not ChatGPT."
)
_TEXT_LIMIT = 160
_HISTORY_TURNS = 8
_HISTORY_CHARS = 4000


@dataclass(frozen=True)
class Reading:
    status: str
    objectives: tuple[tuple[str, str, str], ...]  # action, effect, clipped clause
    side_effects: tuple[tuple[str, str, str], ...]
    reply_only: bool
    dce_route: str
    dce_goals: tuple[str, ...]
    filing_gap: bool

    def decision(self) -> str:
        """``refuse`` (no model), ``constrained`` (model, side effect named), or ``chat``."""
        if self.side_effects and not self.reply_only:
            return "refuse"
        if self.side_effects:
            return "constrained"
        return "chat"


def _clip(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= _TEXT_LIMIT:
        return text
    return text[: _TEXT_LIMIT - 1] + "…"


def _empty(status: str) -> Reading:
    return Reading(status, (), (), False, "unsupported", (), False)


def comprehend(user_text: str) -> Reading:
    """Classify one utterance. A reader failure becomes an empty reading so the turn can still be answered."""
    try:
        ir = parse_request(user_text)
        projection = project_effects(ir)
        dce = parse_dce(user_text)
    except (ValueError, TypeError):
        return _empty("unreadable")
    by_id = {item.node_id: item for item in projection.intents}
    objectives: list[tuple[str, str, str]] = []
    side: list[tuple[str, str, str]] = []
    reply = False
    for objective in ir.graph.objectives:
        intent = by_id.get(objective.id)
        effect = intent.effect if intent is not None else "unknown"
        row = (objective.action, effect, _clip(objective.text))
        objectives.append(row)
        if effect in SIDE_EFFECTS:
            side.append(row)
        elif effect == "reply_only":
            reply = True
    return Reading(
        status=ir.status,
        objectives=tuple(objectives),
        side_effects=tuple(side),
        reply_only=reply,
        dce_route=dce.routing.route,
        dce_goals=tuple(goal.operator for goal in dce.goals),
        filing_gap=dce.routing.route == "graph_candidate",
    )


def identity_reply(user_text: str) -> str | None:
    """A name question is answered here. The pinned model otherwise introduces itself as ChatGPT."""
    if _IDENTITY_RE.search(user_text):
        return IDENTITY_TEXT
    return None


_CAPABILITIES_RE = re.compile(
    r"(?i)^\W*(?:what (?:can|do) you (?:do|offer|support|help (?:me )?with)|what are your (?:capabilities|features|functions|skills)|"
    r"(?:list|show|describe) (?:your )?(?:capabilities|features|skills)|how can you help(?: me)?|what can i (?:ask|do here)|help)\W*$"
)
CAPABILITIES_TEXT = (
    "What I do here:\n"
    "- **Answer from your files** — attach a ZIP or a text file and ask; every answer cites `path:line` in the attachment, "
    "and a follow-up in the same chat (\"And in the public re-run?\") is read against your previous question.\n"
    "- **Extract from a 10-K** — include the token 10-K and an uppercase ticker, for example: Extract the most impactful statements from the latest NVDA 10-K.\n"
    "- **Ordinary conversation** — one reply from the pinned small model, with no invented files, citations or actions.\n"
    "What I do not do: run commands, write or change files, deploy, or fetch pages. A message that asks for that is read back to you and not performed."
)
_ATTACHED_STATE_RE = re.compile(
    r"(?i)\b(?:what(?:'s| is| are| did i| have i)?\s+(?:\w+\s+){0,2}attach(?:ed|ments?)?|which files? (?:are|is|did i|have i) attach|"
    r"did i attach|is (?:anything|a file|the file|the zip|the archive) (?:still )?attached|do you (?:still )?(?:have|see) (?:my|the) (?:file|zip|archive|attachment)s?|"
    r"what files? do you (?:have|see)|(?:which|what) (?:archive|zip|file)s? (?:are you|is) (?:reading|using|working) (?:from|on|with))"
)
_PREVIOUS_ANSWER_RE = re.compile(
    r"(?i)^\W*(?:what (?:did you|was) (?:just )?(?:say|answer|reply|tell me)(?: before| previously| last time)?|repeat (?:that|your (?:last|previous) answer)|"
    r"what was (?:your|the) (?:last|previous) answer|say that again)\W*\??\W*$"
)


def capabilities_reply(user_text: str) -> str | None:
    """A capabilities question is answered from a fixed text; the pinned model would otherwise describe ChatGPT's."""
    if _CAPABILITIES_RE.match(user_text.strip()):
        return CAPABILITIES_TEXT
    return None


def attached_state_reply(user_text: str, prev: Any) -> str | None:
    """Nothing is attached to a conversation-lane turn by definition; say so, and name what the previous turn of this chat was
    answered from when the session knows it (file names only). Never guesses that a file is still attached."""
    if not _ATTACHED_STATE_RE.search(user_text):
        return None
    head = "Nothing is attached to this message, so I am not reading any file right now."
    if prev is not None and getattr(prev, "archives", None):
        names = ", ".join(f"`{a}`" for a in prev.archives)
        return (f"{head} Your previous question in this chat — “{prev.asked}” — was answered from {names}. "
                "Open WebUI keeps a chat's files attached to later messages; if this one came without them, re-attach the file and ask again.")
    return head + " Attach a ZIP or a text file and ask; the answer will cite the file and line."


def previous_answer_reply(user_text: str, prev: Any) -> str | None:
    """“What did you just say?” — the stored head of the previous turn's answer, as a quotation, not a fresh claim."""
    if not _PREVIOUS_ANSWER_RE.match(user_text.strip()):
        return None
    if prev is None or not prev.answer_head:
        return "I have no previous turn for this chat in memory (turns are kept for 30 minutes, in memory only)."
    src = f" (from {', '.join(f'`{a}`' for a in prev.archives)})" if getattr(prev, "archives", None) else ""
    return f"My previous answer in this chat, to “{prev.asked}”{src}, began:\n\n> {prev.answer_head}"


def detached_follow_up_reply(user_text: str, prev: Any, follow_up: Any) -> str | None:
    """An elliptical follow-up (“And in the public re-run?”) that arrived *without* the attachment its predecessor was read
    from: the rewrite is shown and the user is told the file is not in this message — the model is not asked to answer a
    question about a file it cannot see."""
    if follow_up is None or prev is None or not getattr(prev, "archives", None):
        return None
    names = ", ".join(f"`{a}`" for a in prev.archives)
    return (f"I read this as “{follow_up.rewritten}” (a follow-up to “{prev.asked}”), but this message has no attachment — "
            f"your previous answer came from {names}. Re-attach the file (or keep the chat's files attached) and ask again, and I will read it against the file.")


def previous_turn_note(prev: Any) -> str:
    """Reader note for the model: the previous turn of this chat, words and answer head only (no file text)."""
    if prev is None:
        return ""
    src = f" answered from {', '.join(prev.archives)}" if getattr(prev, "archives", None) else ""
    return (f" Previous turn in this chat{src}: the user asked “{prev.asked[:200]}”; the answer began “{prev.answer_head[:200]}”. "
            "Use it only if the user refers back to it; if the new message is about something else, answer that on its own and do "
            "not mention the previous turn or its numbers.")


def scrub_self_claim(text: str) -> str:
    """Drop a first-person ChatGPT or OpenAI claim. Other mentions of those names stay."""
    if _SELF_CLAIM_RE.search(text):
        return IDENTITY_TEXT
    return text


def refusal_text(reading: Reading) -> str:
    lines = ["I will not run, write, or change anything from this message.", "", "Read as:"]
    for action, effect, text in reading.side_effects:
        lines.append(f"- {action} — {effect} — {text}")
    lines.append("")
    lines.append(
        "Ask in words if you want this explained. Attach a ZIP or text file for an answer grounded in your files, "
        "or send a 10-K directive such as: Extract the most impactful statements from the latest NVDA 10-K."
    )
    return "\n".join(lines)


def system_prompt(reading: Reading, previous_note: str = "") -> str:
    goals = ", ".join(reading.dce_goals) or "none"
    effects = ", ".join(f"{action}:{effect}" for action, effect, _ in reading.objectives) or "none"
    extra = ""
    if reading.decision() == "constrained":
        named = ", ".join(sorted({effect for _, effect, _ in reading.side_effects}))
        extra += (
            f" The user also asked for a side effect ({named}). Do not perform it and do not claim you did. "
            "Answer only the part that is a question or an explanation."
        )
    if reading.filing_gap:
        extra += " The message looks like a filing request but it is not a runnable 10-K directive."
    return (
        "You are Forge 2B in conversation. You are not ChatGPT and you were not developed by OpenAI. "
        "If asked who you are, say you are Forge 2B. "
        "This turn has no attached document and is not a SEC filing run. "
        "Answer the latest user message directly. Do not invent file paths, line citations, plan hashes, "
        "or the contents of a filing or archive. Do not claim that you executed a command, wrote a file, or changed a system. "
        "If the user wants an answer taken from their own files, tell them to attach a ZIP or text file. "
        "If they want a 10-K extraction, tell them to include the token 10-K and an uppercase ticker such as NVDA."
        + extra
        + f" Reader note: status {reading.status}; archive goals {goals}; effects {effects}."
        + previous_note
    )


def visible_prefix(reading: Reading) -> str:
    if reading.decision() == "constrained":
        return "I will not run, write, or change anything.\n\n"
    return ""


def footer(reading: Reading) -> str:
    if not reading.filing_gap:
        return ""
    return (
        "\n\n_This looks like a filing request. To run it, include 10-K and an uppercase ticker, "
        "for example: Extract the most impactful statements from the latest NVDA 10-K._"
    )


def flatten_content(content: Any) -> str | None:
    if isinstance(content, list):
        content = "\n".join(
            part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"
        )
    if isinstance(content, str) and content.strip():
        return content
    return None


def conversation(messages: Any) -> list[dict[str, str]]:
    """Recent user and assistant turns, clipped. System and tool messages are left out."""
    if not isinstance(messages, list):
        return []
    out: list[dict[str, str]] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in ("user", "assistant"):
            continue
        text = flatten_content(message.get("content"))
        if text is None:
            continue
        if len(text) > _HISTORY_CHARS:
            text = text[:_HISTORY_CHARS]
        out.append({"role": message["role"], "content": text})
    return out[-_HISTORY_TURNS:]


def trace_reading(reading: Reading) -> dict[str, Any]:
    return {
        "status": reading.status,
        "decision": reading.decision(),
        "objectives": [{"action": action, "effect": effect, "text": text} for action, effect, text in reading.objectives],
        "dce_route": reading.dce_route,
        "dce_goals": list(reading.dce_goals),
        "filing_gap": reading.filing_gap,
    }
