"""Conversation lane for a turn that is not an attachment, a 10-K directive, or the SOURCE fixture.

The request readers classify the latest user message. A side-effect ask with no explanatory
objective is answered from that classification and the model is not called. Every other turn
is one reply from the pinned model, with the classification passed in as a reader note.
Nothing here executes a command, writes a file, or fetches a filing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .dce.parse import parse_request as parse_dce
from .request_ir import parse_request, project_effects

SIDE_EFFECTS = ("artifact_write", "environment_mutation", "command_execution")
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


def system_prompt(reading: Reading) -> str:
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
        "You are Forge 2B in conversation. This turn has no attached document and is not a SEC filing run. "
        "Answer the latest user message directly. Do not invent file paths, line citations, plan hashes, "
        "or the contents of a filing or archive. Do not claim that you executed a command, wrote a file, or changed a system. "
        "If the user wants an answer taken from their own files, tell them to attach a ZIP or text file. "
        "If they want a 10-K extraction, tell them to include the token 10-K and an uppercase ticker such as NVDA."
        + extra
        + f" Reader note: status {reading.status}; archive goals {goals}; effects {effects}."
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
