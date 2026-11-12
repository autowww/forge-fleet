"""Typed D0 operator (Phase 2 item, built in Phase 4): the verdict / decision / status a document states on a labelled line.

Proof packages, decision records and run reports carry their conclusion on a line that names it — ``**Verdict: HOLD**``,
``Decision: GO.``, ``Status: PASS (3/3 gates)``. A reader asking *what is the verdict / decision / status* needs that
line read, not a model's paraphrase of it. ``typed_verdict`` finds every such line in scope, reads the value after the
label and answers with zero model calls when the statements agree; when they disagree it lists each one and chooses none.

Abstains (returns None) when the question is not a what-is-the-<label> question (``Why was the verdict HOLD?`` keeps its
model path), when a content word of the question is explained by none of the candidate lines, their headings or their
file names (``What is the status of item B1?`` is a row question, not a verdict question), when the only labelled lines
are code or table cells, or when no labelled line exists. Nothing here calls a model or performs I/O.
"""
from __future__ import annotations

import re
from typing import Any

from .attachment_map import AttachmentMap
from .retrieval import STOPWORDS, fold, norm
from .lexicon import REQUEST_WORDS

_LABEL_GROUPS = {
    "verdict": {"verdict", "decision", "outcome", "conclusion"},
    "decision": {"verdict", "decision", "outcome", "conclusion"},
    "outcome": {"verdict", "decision", "outcome", "conclusion"},
    "conclusion": {"verdict", "decision", "outcome", "conclusion"},
    "status": {"status"},
}
_LABELS = set().union(*_LABEL_GROUPS.values())
# a what/which question about the label itself; "why", "how", "when", "who" and polar forms keep their model path
_VERDICT_Q_RE = re.compile(r"^\s*(?:what|which)\b(?:(?!\b(?:why|how|when|who|whom)\b).)*?\b(verdict|decision|outcome|conclusion|status)\b", re.I)
# label at the start of the line behind markup only (bold, heading marks, list dash) — a back-ticked `status` is a field
# being documented (live G1R3A: `status`: `ok` · `ok_with_unresolved` in a convention sheet), not a conclusion
_LINE_RE = re.compile(r"^[\s*#>_-]{0,6}(verdict|decision|outcome|conclusion|status)[*_]{0,2}\s*[:—–-]\s*(.+)$", re.I)
_VALUE_END_RE = re.compile(r"\s*(?:\*\*|__|\s[—–-]\s|\(|\.\s|\.$|;|\||$)")
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
# shape words of the question that no line needs to explain
_GENERIC = {"increment", "package", "proof", "evaluation", "final", "overall", "current", "document", "report", "this",
            "record", "run", "release", "review", "assessment", "stated", "state", "states", "given", "reached"}
_MAX_ENTRIES = 6


def _value_of(rest: str) -> tuple[str, str]:
    """``HOLD** — see …`` → (``HOLD``, ``— see …``); ``HOLD (safety gate failed).`` → (``HOLD``, ``(safety gate failed).``)."""
    rest = rest.strip()
    m = _VALUE_END_RE.search(rest, 1)
    value = rest[: m.start()] if m else rest
    value = value.strip().strip("*_`'\" ").rstrip(".,;:!").strip()
    tail = rest[m.start():].strip().lstrip("*_ ").strip() if m else ""
    return value, tail


def _words(s: str) -> set[str]:
    return {fold(w) for w in _WORD_RE.findall(norm(str(s))) if w}


def _content_words(query: str) -> list[str]:
    t = norm(query)
    return list(dict.fromkeys(fold(w) for w in _WORD_RE.findall(t)
                              if w and fold(w) not in STOPWORDS and fold(w) not in REQUEST_WORDS and fold(w) not in _LABELS
                              and fold(w) not in _GENERIC and len(w) > 2))


def _unexplained(words: list[str], explained: set[str]) -> list[str]:
    return [w for w in words if w not in explained
            and not any((w.startswith(e[:5]) or e.startswith(w[:5])) and len(e) > 4 and len(w) > 4 for e in explained)]


# polar form: "Did the blind evaluation pass?", "Was the increment approved?", "Has the gate failed?"
_POLAR_Q_RE = re.compile(r"^\s*(?:did|does|do|is|was|were|has|have|had|are)\b[^?]*\b(pass|passed|passes|succeed|succeeded|approved|accepted|green|met|go|fail|failed|fails|failing|hold|held|rejected|blocked|red)\b", re.I)
_ASKS_POSITIVE = {"pass", "passed", "passes", "succeed", "succeeded", "approved", "accepted", "green", "met", "go"}
_VALUE_NEG = {"hold", "fail", "failed", "failing", "no-go", "nogo", "no go", "rejected", "reject", "blocked", "red", "not passed", "fail"}
_VALUE_POS = {"go", "pass", "passed", "approved", "accepted", "green", "ship", "shipped", "ok", "met", "success", "succeeded"}


def _polarity(value: str) -> str | None:
    v = fold(norm(value)).strip()
    head = v.split()[0] if v else ""
    if v in _VALUE_NEG or head in _VALUE_NEG or v.startswith("not "):
        return "negative"
    if v in _VALUE_POS or head in _VALUE_POS:
        return "positive"
    return None


def typed_verdict(amap: AttachmentMap, files: list[str], query: str) -> dict[str, Any] | None:
    m = _VERDICT_Q_RE.search(query)
    pm = _POLAR_Q_RE.match(query) if not m else None
    if not m and not pm:
        return None
    labels = _LABEL_GROUPS[m.group(1).casefold()] if m else _LABELS
    words = _content_words(query)
    if pm:
        words = [w for w in words if w not in _ASKS_POSITIVE and w not in _VALUE_NEG and w not in _VALUE_POS]
    scope = set(files or [])
    entries: list[dict[str, Any]] = []
    for f in amap.files:
        if f.status != "INCLUDED" or f.duplicate_of or (scope and f.path not in scope):
            continue
        if f.path.lower().rsplit(".", 1)[-1] in ("patch", "diff", "csv", "json", "jsonl", "ndjson", "yaml", "yml", "toml", "ini"):
            continue   # data and config files: a `status:` key there is a field, not the document's conclusion
        for s in amap.segments_for(f.file_id):
            if s.kind in ("code_block", "table_header", "table_row", "header", "row", "diff_file"):
                continue
            ancestry = [norm(str(h)) for h in (s.context.get("heading_ancestry") or [])]
            for i, raw in enumerate(s.text.split("\n")):
                line = raw.strip()
                if not line or line.startswith("|") or line.startswith("```"):
                    continue
                lm = _LINE_RE.match(line)
                if not lm or lm.group(1).casefold() not in labels:
                    continue
                value, tail = _value_of(lm.group(2))
                if not value or len(value.split()) > 6 or value.endswith(":") or "`" in value or "·" in value:
                    continue
                explained = _words(f.path.replace("/", " ").replace(".", " ")) | _words(line)
                for h in ancestry:
                    explained |= _words(h)
                if _unexplained(words, explained):
                    continue
                entries.append({"path": f.path, "line": s.start_line + i, "seg_id": s.seg_id, "label": lm.group(1), "value": value,
                                "tail": tail[:160], "text": line[:240]})
    if not entries:
        return None
    entries = entries[:_MAX_ENTRIES]
    distinct = list(dict.fromkeys(fold(e["value"]) for e in entries))
    if pm:
        # polar: every statement must carry a verdict word of known polarity and agree; the answer is yes/no relative to
        # what the question asks ("did it pass" + HOLD → No; "did it fail" + HOLD → Yes). Live K03 2026-11-06: the model
        # answered "Yes" to "Did the blind evaluation pass?" over a line that says `Verdict: HOLD (safety gate failed)`.
        pols = {_polarity(e["value"]) for e in entries}
        if len(pols) != 1 or None in pols:
            return None
        pol = pols.pop()
        asks_positive = pm.group(1).casefold() in _ASKS_POSITIVE
        yes = (pol == "positive") == asks_positive
        return {"method": "typed_polar_verdict", "answer": "Yes" if yes else "No", "value": entries[0]["value"], "polarity": pol,
                "entries": entries, "note": "" if len(distinct) == 1 else f"stated as {', '.join(distinct)} — same polarity"}
    if len(distinct) == 1:
        return {"method": "typed_verdict", "value": entries[0]["value"], "entries": entries, "note": ""}
    return {"method": "typed_verdict", "value": None, "entries": entries,
            "note": f"{len(entries)} labelled statements carry {len(distinct)} different values; each is listed and none is chosen"}
