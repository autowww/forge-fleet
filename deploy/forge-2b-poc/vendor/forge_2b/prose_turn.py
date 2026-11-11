"""Deterministic prose shape for ordinary chat (mirror of structured_turn for human-readable answers)."""
from __future__ import annotations

import re
from enum import Enum

from .chat_artifacts import strip_chat_artifact
from .chat_lane import Reading
from .dce.structured_turn import contract_kind
from .request_ir import parse_request

_LIST_ITEM = re.compile(r"^\s*(\d+\.|\*|-)\s", re.M)
_HEADING = re.compile(r"^(#{1,3})\s+(.+)$", re.M)
_ENUMERATE_RE = re.compile(
    r"(?i)\b(?:outline|list\s+all|give\s+me\s+the\s+list|all\s+principles|enumerate)\b",
)
_PRIMER_RE = re.compile(
    r"(?i)\b(?:best\s+practices?|principles?\s+of|how\s+does\b.+?\bwork|what\s+are\b.+?\bprinciples?)\b",
)
_PROCEDURE_RE = re.compile(r"(?i)\b(?:workflow|step[s-]?by-?step|how\s+do\s+i)\b")
_COMPARE_RE = re.compile(r"(?i)\bcompare\b|\bvs\.?\b|\bversus\b")
_DECIDE_RE = re.compile(r"(?i)\b(?:should\s+we|which\s+option|recommend)\b")
_TABLE_SHAPE = re.compile(r"(?i)\bas\s+a\s+table\b")


class ProseProfile(str, Enum):
    PLAIN = "plain"
    PRIMER = "primer"
    ENUMERATE = "enumerate"
    PROCEDURE = "procedure"
    COMPARE = "compare"
    DECIDE = "decide"


_PROFILE_HEADINGS: dict[ProseProfile, tuple[str, ...]] = {
    ProseProfile.PRIMER: (
        "Before you start",
        "Core practices",
        "Process and review",
        "When to pause",
        "Anti-patterns",
        "Rule of thumb",
    ),
    ProseProfile.ENUMERATE: ("Overview", "List"),
    ProseProfile.PROCEDURE: ("Prerequisites", "Steps", "Verification"),
    ProseProfile.COMPARE: ("Criteria", "Comparison", "Recommendation"),
    ProseProfile.DECIDE: ("Options", "Criteria", "Recommendation", "Risks"),
}


def prose_profile(reading: Reading, user_text: str) -> ProseProfile:
    """Pick a prose response profile from reader output and the utterance."""
    if contract_kind(user_text or ""):
        return ProseProfile.PLAIN
    goals = {g.lower() for g in reading.dce_goals}
    text = user_text or ""
    if "compare" in goals or _COMPARE_RE.search(text):
        return ProseProfile.COMPARE
    if "recommend" in goals:
        return ProseProfile.DECIDE
    if {"list", "inspect"} & goals or _ENUMERATE_RE.search(text):
        return ProseProfile.ENUMERATE
    if _PROCEDURE_RE.search(text):
        return ProseProfile.PROCEDURE
    try:
        ir = parse_request(text)
        for obj in ir.graph.objectives:
            if obj.output_shape is not None and _TABLE_SHAPE.search(obj.output_shape.text):
                return ProseProfile.COMPARE
    except (ValueError, TypeError):
        pass
    if {"explain", "summarize", "describe"} & goals or _PRIMER_RE.search(text):
        return ProseProfile.PRIMER
    return ProseProfile.PLAIN


def profile_instruction(profile: ProseProfile) -> str:
    if profile == ProseProfile.PLAIN:
        return " Use clear Markdown. Do not output HTML, live graphs, or execution timelines."
    titles = _PROFILE_HEADINGS.get(profile)
    if not titles:
        return " Use clear Markdown. Do not output HTML, live graphs, or execution timelines."
    joined = " → ".join(f"## {t}" for t in titles)
    extra = ""
    if profile == ProseProfile.ENUMERATE:
        extra = " The final section must be a numbered list covering every item requested."
    elif profile == ProseProfile.COMPARE:
        extra = " Prefer a small Markdown table when it aids scanning."
    return (
        f" Shape the answer with these H2 sections in order: {joined}."
        f"{extra} Do not output HTML, live graphs, or execution timelines."
    )


def _bucket_sections(text: str) -> dict[str, str]:
    """Split on H2; keys are normalized lower headings."""
    parts: dict[str, str] = {}
    current_key = "__lead__"
    buf: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+)$", line.strip())
        if m:
            if buf:
                parts[current_key] = "\n".join(buf).strip()
            current_key = m.group(1).strip().lower()
            buf = []
        else:
            buf.append(line)
    if buf:
        parts[current_key] = "\n".join(buf).strip()
    return parts


def _reorder_headings(text: str, profile: ProseProfile) -> str:
    canon = _PROFILE_HEADINGS.get(profile)
    if not canon:
        return text
    buckets = _bucket_sections(text)
    lead = buckets.pop("__lead__", "")
    blocks: list[str] = []
    if lead:
        blocks.append(lead)
    used: set[str] = set()
    for title in canon:
        key = title.lower()
        body = buckets.get(key)
        if body is None:
            for k, v in buckets.items():
                if k not in used and (key in k or k in key):
                    body, key = v, k
                    break
        if body:
            used.add(key)
            blocks.append(f"## {title}\n\n{body}")
    for k, v in buckets.items():
        if k not in used:
            blocks.append(f"## {k.title()}\n\n{v}")
    return "\n\n".join(blocks).strip() if blocks else text


def assemble_prose(profile: ProseProfile, raw: str) -> str:
    text = strip_chat_artifact(raw or "")
    if profile in _PROFILE_HEADINGS:
        text = _reorder_headings(text, profile)
    return text.strip()


_LIST_PRESENT = _LIST_ITEM


def gate(profile: ProseProfile, text: str, *, truncated: bool = False) -> list[str]:
    fails: list[str] = []
    low = (text or "").lower()
    if "<!doctype html" in low or "**live timeline:**" in low:
        fails.append("artifact_leak")
    if truncated:
        fails.append("truncated_outline")
    if profile == ProseProfile.ENUMERATE and _LIST_PRESENT.search(text or "") is None:
        fails.append("list_missing")
    return fails


def enumerate_retry_user_message() -> str:
    return "Output only the numbered list requested. Plain Markdown only; no HTML and no live graphs."
