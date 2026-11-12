"""Comprehension helpers for chat DAG: compound objectives and graph nodes."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .chat_lane import Reading
from .request_ir import parse_request

if TYPE_CHECKING:
    from .execution_graph import ExecutionGraph

_COMPOUND = re.compile(
    r"(?i)(?:principles?|practices?|basics?).{0,80}\band\b.{0,40}\b(?:how|turn|build|design|make|create)\b",
)
_HOW_TURN = re.compile(r"(?i)\bhow\s+(?:do\s+)?i\s+turn\b|\bhow\s+to\s+(?:build|design|make|create)\b")


@dataclass(frozen=True)
class ScopedObjective:
    id: str
    label: str
    user_slice: str
    effect: str = "reply_only"


def expanded_objectives(user_text: str, reading: Reading) -> list[ScopedObjective]:
    """Return plan objectives: IR rows plus synthetic second clause when compound ask detected."""
    out: list[ScopedObjective] = []
    for i, (action, effect, text) in enumerate(reading.objectives):
        out.append(ScopedObjective(f"obj_{i}", f"{action}:{effect}", text or user_text[:120], effect))
    text = user_text.strip()
    if len(out) >= 2:
        return out[:6]
    if _COMPOUND.search(text) or _HOW_TURN.search(text):
        if not out:
            out.append(ScopedObjective("obj_0", "explain:reply_only", "Core principles or practices", "reply_only"))
        second = "How to turn those into a concrete architecture or platform design"
        if _HOW_TURN.search(text):
            m = _HOW_TURN.search(text)
            if m:
                second = text[m.start() : min(len(text), m.start() + 140)].strip()
        out.append(ScopedObjective("obj_1", "design:reply_only", second, "reply_only"))
        return out
    try:
        ir = parse_request(text)
        if len(ir.graph.objectives) >= 2:
            for i, obj in enumerate(ir.graph.objectives[:6]):
                if any(o.id == f"obj_{i}" for o in out):
                    continue
                out.append(
                    ScopedObjective(f"obj_ir_{i}", f"{obj.action}:reply_only", obj.text[:120], "reply_only")
                )
    except (ValueError, TypeError):
        pass
    if not out:
        out.append(ScopedObjective("obj_0", "chat:reply_only", text[:160], "reply_only"))
    return out[:6]


def emit_comprehension_band(eg: ExecutionGraph, user_text: str, reading: Reading, decision: str) -> list[ScopedObjective]:
    """Add comprehension-lane nodes and edges; return objectives for planning."""
    eg.add("utterance", "zero_model", "user message", lane="comprehend", kind="utterance")
    eg.finish("utterance", "COMMITTED", user_text[:80] + ("…" if len(user_text) > 80 else ""))
    objectives = expanded_objectives(user_text, reading)
    prev = "utterance"
    for obj in objectives:
        eg.add(obj.id, "zero_model", "request_ir objective", lane="comprehend", kind="objective")
        eg.finish(obj.id, "COMMITTED", obj.label + " · " + obj.user_slice[:50])
        eg.add_edge(prev, obj.id)
        prev = obj.id
    eg.add("route", "zero_model", "DCE-01 route", lane="comprehend", kind="route")
    eg.finish(
        "route",
        "COMMITTED",
        f"decision {decision} · {reading.dce_route} · goals {','.join(reading.dce_goals[:4]) or '—'}",
    )
    eg.add_edge(prev, "route")
    return objectives
