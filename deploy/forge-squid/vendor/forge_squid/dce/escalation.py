"""Model-facing half of the DCE ``on`` lane: the Q2 contract, the deterministic guards that decide whether a model reply
is accepted, re-asked or demoted, and the D1 / D2 / compare node runners that apply them.

Nothing here decides *what* to ask — that is the DAG (``dag.py``) and the deterministic operators (``tables.py``). This
module decides whether the fixed model's answer may be shown as COMMITTED, and spends at most the run's call budget doing
so. Every guard is deterministic and every re-ask is bounded to one further call:

* ``q2_decide``            — the JSON ``{found, answer, quotes}`` contract with verbatim quote verification and the
                             DCE-only quote repairs (``attach.verify_quotes(repair=True)``).
* ``covering_excerpts``    — a ``found: false`` is re-asked once when an excerpt carries most of the question's words.
* ``quote_relevance``      — a verbatim quote that shares no term with the question is re-asked over the on-topic lines.
* ``numbers_not_in_quotes``— a number the quoted lines do not carry makes the node PARTIAL (the sentence is the model's).
* polar qualification      — a bare yes/no whose other side is written in a covering line is stated with that line (PARTIAL).
* polar completion         — a yes/no answer shows the other covering lines, marked as not quoted by the model.
* pointer answer           — a sentence that is only a file pointer is replaced by the quoted line's own statement.

Nothing in this module performs I/O; the model is reached only through the ``LlmCall`` the facade passes in.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from .. import attach, zipingest
from . import aliases, lexicon, retrieval, verdicts
from .untrusted import scan_text

if TYPE_CHECKING:  # pragma: no cover — the runners mutate the executor's NodeResult; no runtime import cycle
    from .shadow import Budget, NodeResult, Plan

log = logging.getLogger("forge_squid.dce")

LlmCall = Callable[..., Awaitable[tuple[str, str]]]   # (messages, *, max_tokens=Q2_MAX_TOKENS) -> (content, served_model)
Q2_MAX_TOKENS = 400          # the legacy contract's completion budget
Q2_MAX_TOKENS_RETRY = 900    # second attempt after an object the token limit cut (qwen3.5 spends part of the budget on reasoning)


@dataclass
class Calls:
    """Per-run model-call ledger shared by every node runner (``budget.max_model_calls`` is the cap)."""
    cap: int
    used: int = 0

    @property
    def exhausted(self) -> bool:
        return self.used >= self.cap

    def charge(self, attempts: list[dict[str, Any]]) -> None:
        self.used += len(attempts)

    def budget_note(self) -> str:
        return f"model-call budget exhausted ({self.used}/{self.cap})"


# --- the Q2 contract ------------------------------------------------------------------------------------------------------------
async def q2_decide(call_llm: LlmCall, question: str, hits: list[attach.Hit], *, max_attempts: int,
                    user_tail: str | None = None) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """The existing fixed-model Q2 contract (JSON {found, answer, quotes}) with verbatim-quote verification. Unchanged schema.
    ``user_tail`` is an optional directive appended to the first user turn (the escalation re-asks use it)."""
    hint: str | None = None
    json_only = False
    max_tokens = Q2_MAX_TOKENS
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, max_attempts + 1):
        msgs = attach.qa_messages(question, hits, retry_hint=hint, json_only=json_only, user_tail=user_tail)
        t0 = time.monotonic()
        try:
            content, served = await call_llm(msgs, max_tokens=max_tokens)
        except Exception as ex:  # noqa: BLE001 — upstream failure is recorded, never raised into the response body
            attempts.append({"attempt": attempt, "failure": f"UPSTREAM:{type(ex).__name__}"})
            hint = "upstream error"
            continue
        ms = int((time.monotonic() - t0) * 1000)
        try:
            cand = attach.parse_qa(content)
        except (ValueError, json.JSONDecodeError) as ex:
            reason = str(ex)
            attempts.append({"attempt": attempt, "failure": f"DECISION_INVALID:{reason[:60]}", "ms": ms, "max_tokens": max_tokens})
            # server log only (never the trace): the shape of what the 2B model emitted instead of the JSON object
            log.warning("dce q2 attempt %d rejected %s: served=%s chars=%d head=%r", attempt, reason[:60], served, len(content), content[:160])
            hint = reason[:80]
            # the retry must differ from the first call in what the model *sees*, or a temperature-0 model repeats itself
            # byte for byte (live 2026-11-06): prose → the JSON-only directive at the end of the user turn; an object cut
            # by the token limit → a larger completion budget. Both stay within the node's call budget (this is attempt 2).
            json_only = True   # prose, prose around a half-object, wrong shape: the directive is the one lever that changed the live answer
            if reason.startswith("truncated JSON object"):
                max_tokens = Q2_MAX_TOKENS_RETRY
            continue
        salvaged = cand.pop("salvaged", None)
        problems = attach.verify_quotes(cand, hits, repair=True)
        repaired = [f"{q['path']}:{q['line']}={q.pop('repaired')}" for q in cand["quotes"] if q.get("repaired")]
        if problems:
            attempts.append({"attempt": attempt, "failure": "QUOTE_NOT_VERBATIM", "problems": problems[:3], "ms": ms})
            hint = problems[0]
            # same lesson as above: the system-prompt hint alone left the second reply identical (live K18 2026-11-06:
            # `found: true`, `quotes: []`, twice) — the quoting directive goes at the end of the user turn
            user_tail = attach.QUOTE_TAIL
            continue
        cand["found"] = bool(cand["quotes"])
        attempts.append({"attempt": attempt, "status": "COMMITTED", "ms": ms, "served": served,
                         "prompt_sha256": hashlib.sha256(json.dumps(msgs, sort_keys=True).encode()).hexdigest(),
                         **({"salvaged": salvaged} if salvaged else {}), **({"repaired": repaired} if repaired else {}),
                         **({"max_tokens": max_tokens} if max_tokens != Q2_MAX_TOKENS else {})})
        return cand, attempts
    return None, attempts


# --- deterministic guards --------------------------------------------------------------------------------------------------------
# Request verbs / shape words that carry no content ("find README.md, quote its exact sentinel" → content term = sentinel).
_REQUEST_WORDS = lexicon.REQUEST_WORDS

_HEADING_RE = re.compile(r"^\s*(#{1,6}\s+\S|[A-Z][\w &/-]{0,60}:?\s*$|={3,}|-{3,})")
_DATE_RE = re.compile(r"\b\d{4}-\d{2}(-\d{2})?\b|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.? \d{1,4}\b|\bq[1-4] \d{4}\b", re.I)
_VERSION_RE = re.compile(r"\bv?\d+\.\d+(\.\d+)?\b")


def _is_bare_title(text: str) -> bool:
    """A line with no value signal: no digit, no key/value or list punctuation, at most four words."""
    t = text.strip()
    return bool(t) and not re.search(r"[\d:=,|\"'()\[\]{}<>]", t) and len(t.split()) <= 4


def _is_title_like(text: str) -> bool:
    return bool(_HEADING_RE.match(text) or _is_bare_title(text))


_ANSWER_NUM_RE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*(?![\w.])")


_ANSWER_HASH_RE = re.compile(r"(?<![\w/.-])(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}(?![\w/.-])", re.I)


def numbers_not_in_quotes(answer: str, quoted_texts: list[str]) -> list[str]:
    """Numbers the answer states that occur in none of the quoted lines (decimal comma and dot, thousands separators
    folded; a bare integer also matches `n/m`, `n%` and `(n)` forms since they are substrings). Empty = every number
    in the sentence is carried by a quote."""
    hay = " ".join(quoted_texts).replace(",", ".").replace("\u00a0", " ")
    hay_tokens = set(re.findall(r"\d+(?:\.\d+)*", hay))
    loose = []
    # a commit hash is a number in this sense (live K17 after30, 2026-11-06: "Commit 097b06a" quoting `frozen_utc: …`):
    # a hash the answer states that no quoted line carries is as unsupported as a bare count
    hashes = [h for h in _ANSWER_HASH_RE.findall(answer) if not any(h.casefold() in t.casefold() for t in quoted_texts)]
    for m in _ANSWER_NUM_RE.findall(_ANSWER_HASH_RE.sub(" ", answer)):
        n = m.replace(",", ".")
        if n in hay_tokens or any(t.startswith(n + ".") or t.endswith("." + n) or t == n.strip("0") for t in hay_tokens):
            continue
        loose.append(m)
    return list(dict.fromkeys(hashes + loose))


def quote_relevance_gap(plan: Plan, question: str, quoted: list[dict[str, Any]], hits: list[attach.Hit]) -> str | None:
    """Deterministic guard for a quote that is verbatim-correct but off-topic (observed live 2026-11-05: a 2B model asked to
    'find README.md, quote its exact sentinel' quoted the README title line). Returns a detail string when none of the
    quoted lines shares a content term (or its alias / typo-corrected / 5-char-stem variant) with the question while at
    least one retrieved excerpt does; None otherwise (no content terms, or the quote is on topic). Never calls a model."""
    return quote_relevance(plan, question, quoted, hits)[0]


def _content_terms(plan: Plan, question: str, *, keep_file_words: bool = False) -> tuple[list[str], Callable[[str, str], bool], list[str]]:
    """The question's content terms (request words, file-name words, numbers and excluded/negated parts removed), a
    ``mentions(text, term)`` test that accepts the term, its typo repair, its curated alias phrases and inflections, and
    the question's anchors. Shared by the quote-relevance guard and the not-found escalation."""
    # what the user excluded ("other than the health endpoint", "but not the README") is not a content term to look for
    q = lexicon.EXCLUSION_RE.sub(" ", question)
    q = lexicon.NEGATION_RE.sub(" ", q)
    terms, expanded, typo, anchors = plan.retriever.analyze(q)
    file_words: set[str] = set()
    for f in plan.amap.files:
        for part in re.split(r"[/.\-_]", retrieval.norm(f.path)):
            if part:
                file_words.add(part)
    content = [t for t in terms if t not in _REQUEST_WORDS and (keep_file_words or t not in file_words) and not t.isdigit()]
    table = getattr(plan.retriever, "alias_table", None)

    def variants(t: str) -> list[str]:
        # `expanded` is {canonical_key: [query phrases that triggered it]}; a term inherits its key and the key's alias phrases
        keys = [k for k, phrases in expanded.items() if any(t in p.split() for p in phrases)]
        out = [t, typo.get(t, t)] + keys + [p for k in keys for p in aliases.expansions_for_key(k, table)]
        return list(dict.fromkeys(retrieval.fold(v) for v in out if v))

    def mentions(text: str, t: str) -> bool:
        ft = retrieval.fold(retrieval.norm(text))
        words = set(re.findall(r"\w+", ft))
        for v in variants(t):
            if len(v) < 4:
                if v in words:   # a short alias (`uk`, `en`, `tz`) counts only as a whole word, never inside another
                    return True
                continue
            if v in ft:
                return True
            if any(len(w) >= 4 and (w.startswith(v[:5]) or v.startswith(w[:5])) for w in words):
                return True   # inflection: tests/test, passed/pass, released/release
        return False

    return content, mentions, anchors


def covering_excerpts(plan: Plan, question: str, hits: list[attach.Hit]) -> tuple[list[tuple[attach.Hit, list[str]]], list[str]]:
    """Excerpt lines that carry most of the question's content terms — all of them when the question has three or fewer,
    otherwise at least two thirds — the deterministic trigger for not accepting a model's ``found: false`` at once.
    Half was too loose (live K36 2026-11-06: "production database password" re-asked over a line about *rotating* the
    database password, and the model then quoted it as the answer to an absent question). Returns ``[(hit, covered_terms)]``
    best first, plus the content terms. Words that are also file-name parts stay in (``blind`` in a package with a
    ``BLIND/`` folder is still what "who labelled the blind set" is about — live K16: the covering line was excerpt 1 and
    the trigger never fired because only ``labelled`` was left)."""
    content, mentions, _anchors = _content_terms(plan, question, keep_file_words=True)
    if len(content) < 2:
        return [], content
    need = len(content) if len(content) <= 3 else max(3, -(-2 * len(content) // 3))
    headings = _heading_ancestry(plan)
    scored = []
    for h in hits:
        covered = [t for t in content if mentions(h.text, t)]
        if len(covered) >= 2 and len(covered) < need:
            # a body line is read under its section heading (live K27 2026-11-06: `may be logged in shadow … provided no
            # decision` sits under "What may be consumed now (read-only, no decisions)" — the heading carries the question's
            # `consumed now`, the line its `effect … shadow`). The line must carry two terms of its own; the heading only tops up.
            head = headings.get((h.path, h.line), "")
            covered += [t for t in content if t not in covered and head and mentions(head, t)]
        if len(covered) >= need:
            scored.append((h, covered))
    scored.sort(key=lambda hc: -len(hc[1]))
    return scored, content


def _heading_ancestry(plan: Plan) -> dict[tuple[str, int], str]:
    """``(path, line) -> heading ancestry`` for every indexed non-heading line (empty for CSV/JSON rows and headings)."""
    out: dict[tuple[str, int], str] = {}
    for r in getattr(plan.retriever, "rows", []):
        if r.kind != "heading" and r.heading:
            out[(r.path, r.line)] = r.heading
    return out


def quote_relevance(plan: Plan, question: str, quoted: list[dict[str, Any]], hits: list[attach.Hit]) -> tuple[str | None, list[attach.Hit]]:
    """`quote_relevance_gap` plus the on-topic excerpts it found (the lines that share a content term with the question and
    were not quoted). The executor re-asks the model once over exactly those lines (`q2_on_topic_retry`)."""
    content, mentions, _anchors = _content_terms(plan, question)
    if not content:
        return None, []

    quoted_texts = [str(q.get("text", "")) for q in quoted]
    # a table header quoted for a question that names a row by its code ("item B1", "case E040"; live K25 2026-11-06:
    # `| # | item | acceptance … |` quoted, the `| B1 | … |` row was the first excerpt): the header is a label, the row
    # carrying the code is the on-topic line → re-ask over the rows that carry it
    codes = {retrieval.fold(c) for c in retrieval._CODE_RE.findall(question)} | {retrieval.fold(i) for i in retrieval._IDENT_RE.findall(question)}
    if codes and all(txt.lstrip().startswith("|") for txt in quoted_texts) and not any(c in retrieval.fold(retrieval.norm(txt)) for c in codes for txt in quoted_texts):
        rows = [h for h in hits if h.text.lstrip().startswith("|") and any(c in retrieval.fold(retrieval.norm(h.text)) for c in codes)
                and not any(h.path == q.get("path") and h.line == q.get("line") for q in quoted)]
        if rows:
            return (f"quoted table header carries none of the question's identifiers ({', '.join(sorted(codes)[:3])}); row "
                    + ", ".join(f"`{h.path}:{h.line}`" for h in rows[:3]) + " does — the quote is verbatim but is the label, not the row"), rows
    if any(mentions(txt, t) for txt in quoted_texts for t in content):
        return None, []
    # anchors (versions, identifiers, quoted strings, numbers) in the quote make it on-topic even without a shared word
    if any(retrieval.fold(a) in retrieval.fold(retrieval.norm(txt)) for a in _anchors for txt in quoted_texts):
        return None, []
    # the question names a category; the quote is an instance of it (a heading for "which section", a date for "which month")
    cset = set(content)
    if cset & {"section", "sections", "heading", "headings", "title", "chapter"} and any(_HEADING_RE.match(txt) for txt in quoted_texts):
        return None, []
    if cset & {"month", "date", "dates", "year", "day", "when", "released", "release", "time"} and any(_DATE_RE.search(txt) for txt in quoted_texts):
        return None, []
    if cset & {"version", "versions", "release", "released"} and any(_VERSION_RE.search(txt) for txt in quoted_texts):
        return None, []
    better = [h for h in hits if any(mentions(h.text, t) for t in content) and not any(h.path == q.get("path") and h.line == q.get("line") for q in quoted)]
    if not better:
        return None, []
    if not all(_is_title_like(txt) for txt in quoted_texts):
        # a content line that shares no term and no anchor with the question is off-topic only when a sibling excerpt
        # carries at least half of the question's terms (Granite smoke `port` after P3, 2026-11-06: `The service name is
        # forge-zip-demo.` quoted for "the deployment port" while `Use port 18473 …` was the line above it)
        # … together with a concrete value (a number): a label line alone (`def health():`, a CSV header) is what the
        # quoted body line belongs to, not a competitor (oracle C051, C019)
        need = max(1, (len(content) + 1) // 2)
        if not any(sum(1 for t in content if mentions(h.text, t)) >= need and re.search(r"\d", h.text) and not _HEADING_RE.match(h.text) for h in better):
            return None, []
    return (f"quoted line(s) share no term with the question ({', '.join(content[:4])}); retrieved excerpt "
            + ", ".join(f"`{h.path}:{h.line}`" for h in better[:3]) + " does — the quote is verbatim but may be off-topic, so the goal is not committed"), better


# --- excerpt builders ------------------------------------------------------------------------------------------------------------
_BLOCK_SPAN_LINES = 4   # excerpt lines a multi-line (block) span may contribute: the lines that carry a question token, else its head


def hits_from_spans(plan: Plan, entry: dict[str, Any], *, max_chars: int = 3200, question: str = "") -> list[attach.Hit]:
    """Map-verified spans → excerpt *lines* (the Q2 contract is path:line: text). A span that is a sub-line structure
    (JSON key, CSV cell) yields its whole source line; a multi-line span yields the lines that carry a question token
    (else its first lines), at most ``_BLOCK_SPAN_LINES`` — live K25 2026-11-06: one 28-line `HASHES.txt` block matched
    on the word "next" and flooded the prompt. Lines the untrusted-instruction lexicon flags are withheld from the model
    (they stay citable through the audit node, never as context)."""
    hits: list[attach.Hit] = []
    seen: set[tuple[str, int]] = set()
    total = 0
    toks = {retrieval.fold(w) for w in re.findall(r"[^\W_]+", question) if len(w) > 2 and w.casefold() not in retrieval.STOPWORDS} if question else set()
    for s in entry.get("spans", []):
        loc = plan.amap.resolve(s["seg_id"], plan.scope)          # raises if the pointer does not round-trip → node FAILED
        text = plan.amap.text_of(loc["file_id"])
        lines = text.split("\n") if text is not None else loc["text"].split("\n")
        span_lines = list(range(loc["start_line"], loc["end_line"] + 1))
        if len(span_lines) > _BLOCK_SPAN_LINES:
            def _line(ln: int) -> str:
                return lines[ln - 1] if text is not None and 0 < ln <= len(lines) else loc["text"].split("\n")[ln - loc["start_line"]]
            carrying = [ln for ln in span_lines if toks and (toks & {retrieval.fold(w) for w in re.findall(r"[^\W_]+", _line(ln))})]
            span_lines = (carrying or [ln for ln in span_lines if _line(ln).strip()])[:_BLOCK_SPAN_LINES]
        for ln in span_lines:
            line = lines[ln - 1] if text is not None and 0 < ln <= len(lines) else loc["text"].split("\n")[ln - loc["start_line"]]
            if not line.strip() or (loc["path"], ln) in seen or scan_text(line):
                continue
            seen.add((loc["path"], ln))
            total += len(line)
            if total > max_chars:
                return hits
            hits.append(attach.Hit(loc["path"], ln, line, float(s["score"])))
    return hits


_RULE_LINE_RE = re.compile(r"^\s*(?:\|?\s*:?-{2,}:?\s*)+\|?\s*$|^\s*[-=*_]{3,}\s*$")   # markdown table rules / horizontal rules


def file_head_hits(plan: Plan, paths: list[str], *, max_lines: int = 8, max_chars: int = 3200) -> list[attach.Hit]:
    """Leading content lines of named files (headings first, then prose) as excerpts — the D2 fallback when a
    recommend/summarize goal is scoped to a file but its question carries no retrievable word ("What should we do
    next?" → `06_NEXT_RECOMMENDATION.md`; live K24 2026-11-06 failed with zero calls). Lines the untrusted lexicon
    flags are withheld, as everywhere else."""
    hits: list[attach.Hit] = []
    total = 0
    by_path = {f.path: f for f in plan.amap.files if f.status == "INCLUDED"}
    for p in paths:
        f = by_path.get(p)
        text = plan.amap.text_of(f.file_id) if f else None
        if text is None:
            continue
        lines = text.split("\n")
        picked = [ln for ln, line in enumerate(lines, 1) if line.strip() and not _RULE_LINE_RE.match(line)][:max_lines]
        for ln in picked:
            line = lines[ln - 1]
            if scan_text(line):
                continue
            total += len(line)
            if total > max_chars:
                return hits
            hits.append(attach.Hit(p, ln, line[:400], 1.0))
    return hits


def spans_of(hits: list[attach.Hit], quotes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"path": q["path"], "line": q["line"], "text": q["text"]} for q in quotes]


# --- node runners (mutate the executor's NodeResult in place) ------------------------------------------------------------------------
async def run_d2(r: NodeResult, n: Any, e: dict[str, Any], plan: Plan, ings: list[zipingest.Ingest], results: dict[str, NodeResult],
                 call_llm: LlmCall | None, budget: Budget, calls: Calls) -> None:
    """D2 (summarize / recommend): one bounded Q2 call over spans already verified by the nodes it depends on, else over
    its own retrieval, else over the lead files' heads. Always PARTIAL — quote correctness alone does not prove entailment."""
    deps_spans = [s for d in n.depends_on for s in results[d].spans if d in results and results[d].status == "COMMITTED"]
    hits = [attach.Hit(s["path"], s["line"], s["text"], 1.0) for s in deps_spans][:8] or (hits_from_spans(plan, e, question=n.query) if e.get("status") == "FOUND" else [])
    named = list(n.source_scope.get("files") or n.source_scope.get("focus") or [])   # hard scope, else the inferred file
    if n.kind == "summarize" and not named and not deps_spans:
        # a package-wide summary has no retrievable words ("summarize", "three sentences"): the excerpts are the
        # leading lines of the lead files in overview order (README, decision, …), as the legacy overview lane
        # reads them — live K05 2026-11-06 retrieved noise, quoted nothing and showed an empty summary
        lead = [h.path for h in attach.overview_hits(ings, max_hits=3)]
        hits = file_head_hits(plan, lead, max_lines=5)
        r.method = "lead_file_head_lines" if hits else ""
    if not hits and named:
        hits = file_head_hits(plan, named)   # the named file's leading lines (deterministic, bounded)
        r.method = "file_head_lines" if hits else ""
    if not hits and n.kind == "summarize":
        hits = [h for h in attach.overview_hits(ings) if not scan_text(h.text)]   # headline line per file, as the legacy overview
        r.method = "overview_lines"
    r.route = "D2"
    if not hits:
        r.status, r.detail = "FAILED", n.failure
        return
    if call_llm is None or calls.exhausted:
        r.status, r.detail = "SKIPPED", calls.budget_note()
        return
    q = ("Based only on these excerpts, " + n.query.strip().rstrip(".") + ". Quote the excerpt lines your answer rests on.")
    dec, r.attempts = await q2_decide(call_llm, q, hits, max_attempts=budget.max_attempts)
    calls.charge(r.attempts)
    r.model_calls = len(r.attempts)
    if dec is None and n.kind == "summarize":
        # the model produced nothing verifiable in its attempts (live M01 G1R3E, 2026-11-06: two attempts, 20 s, FAILED and
        # an empty page). A summary node does not fail silently: the lead lines the model was shown are stated verbatim
        # as the package's own opening, PARTIAL, and the verdict lead below still applies — nothing generated.
        shown = [h for h in hits if not _is_title_like(h.text)][:4] or hits[:4]
        r.status, r.method = "PARTIAL", "lead_lines_verbatim" + ("_" + r.method if r.method else "")
        r.answer = (f"The model gave no verifiable summary in {len(r.attempts)} attempt(s); the package's own opening lines, verbatim:\n"
                    + "\n".join(f"- `{h.path}:{h.line}` — {_line_statement(h.text) or h.text.strip()[:300]}" for h in shown))
        r.spans = [{"path": h.path, "line": h.line, "text": h.text} for h in shown]
        r.detail = "no verifiable model output; lead lines shown verbatim, nothing generated"
        dec = {"answer": r.answer, "quotes": []}
        gated = False
    elif dec is None:
        r.status, r.detail = "FAILED", "no verifiable model output"
        return
    else:
        r.status, r.method = "PARTIAL", "q2_over_" + (r.method or "verified_spans")
        gated = True
    quoted_texts = [str(qq.get("text", "")) for qq in dec["quotes"]]
    body_hits = [h for h in hits if not _is_title_like(h.text)]
    if quoted_texts and all(_is_title_like(t) for t in quoted_texts) and body_hits and not calls.exhausted:
        # every quote is a bare title although content lines were in front of the model (live K24 2026-11-06:
        # "What should we do next?" → `# 06 — Next recommendation`, answer "HOLD"; line 3 names the follow-up).
        # One bounded re-ask over the content lines only; a verified quote there replaces the title answer.
        dec2, att2 = await q2_decide(call_llm, q, body_hits[:8], max_attempts=1)
        calls.charge(att2)
        r.model_calls += len(att2)
        r.attempts = r.attempts + att2
        if dec2 and dec2["quotes"]:
            dec = dec2
            r.method += "_body_retry"
    if gated:
        r.answer, r.spans = dec["answer"], spans_of(hits, dec["quotes"])
        r.detail = "quotes verified verbatim; the reasoning itself is model output and is not deterministically entailed"
    if not gated:
        pass
    elif not r.answer.strip():
        r.answer = (f"The model produced no {'summary' if n.kind == 'summarize' else 'recommendation'} over the {len(hits)} excerpt(s) it was shown"
                    + (" and quoted nothing" if not dec["quotes"] else "") + "; nothing is claimed.")
        r.detail = "model returned an empty answer; " + r.detail
    elif budget.d2_mode != "off":
        _d2_sentence_gate(r, n, plan, budget.d2_mode)
    if n.kind == "summarize":
        # a summary leads with the labelled verdict of what it summarizes when one is stated — the package's when no file
        # is named, the named file's otherwise (live K05 2026-11-06: three model sentences, none naming the HOLD; K41 the
        # same over `04_BLIND_EVALUATION.md`, which carries its own `Verdict: HOLD` line); read from the line, no model
        tv = verdicts.typed_verdict(plan.amap, named, "What is the verdict?")
        if tv and tv.get("value"):
            lead = tv["entries"][0]
            r.answer = (f"**{lead['label']}: {tv['value']}** (`{lead['path']}:{lead['line']}`; stated on {len(tv['entries'])} labelled line(s), read from the line)\n\n" + r.answer)
            r.spans = [{"path": en["path"], "line": en["line"], "text": en["text"]} for en in tv["entries"][:2]] + r.spans
            r.method += "+verdict_fact"
            if verdicts._polarity(tv["value"]) == "negative":
                _gates_fact(r, plan, named)


def _gates_fact(r: NodeResult, plan: Plan, named: list[str]) -> None:
    # a summary of a *failed* evaluation leads with what failed, read from the gate table (D0, `tables.typed_table_filter`),
    # after the verdict line: "Summarize the sealed evaluation outcome in two sentences" (live L34 G1R3D, K41 G1R3A,
    # 2026-11-06) wants the failure counts in a *stated* sentence, and the model's own two sentences are pruned by the
    # strict D2 gate as often as they are kept. The filter is scoped to the named file when the summary names one; a
    # package whose verdict table shows no failed row adds nothing.
    from . import tables
    q = "Which gates failed" + (f" in {named[0]}" if len(named) == 1 else "") + "?"
    tf = tables.typed_table_filter(plan.amap, q)
    if not tf or not tf["tables"] or not tf["tables"][0]["entries"]:
        return
    t = tf["tables"][0]
    parts = []
    for en in t["entries"][:8]:
        cells = "; ".join(f"{c['column']} {c['value']}" for c in en["cells"] if c["value"])
        parts.append(f"{en['label']}" + (f" ({cells})" if cells else ""))
    where = f"`{t['path']}:{t['entries'][0]['line']}`" + (f"–{t['entries'][-1]['line']}" if len(t["entries"]) > 1 else "")
    r.answer = r.answer.replace("\n\n", f"\n\n**Failed gates** ({len(t['entries'])} of {t['rows_considered']} rows, read from the table {where}): " + "; ".join(parts) + ".\n\n", 1)
    r.spans = r.spans + [{"path": t["path"], "line": en["line"], "text": "", "seg_id": en.get("seg_id", "")} for en in t["entries"][:8]]
    r.method += "+gates_fact"


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZА-ЯІЇЄҐ\"'(*`\d])")


def d2_sentence_entailment(plan: Plan, answer: str, spans: list[dict[str, Any]]) -> tuple[list[str], list[tuple[str, str]]]:
    """Decision 2 (2026-11-06): the model's D2 reasoning, sentence by sentence, against the lines it quoted. A sentence is
    *entailed* when one quoted line carries every number it states (decimal comma/dot folded) **and** at least two thirds
    of its content words (stem / typo / curated alias, same `mentions` test as the guards) — both on the *same* line, so a
    number from one line cannot be glued to a subject from another. A sentence with no number and no content word claims
    nothing and is kept. Returns ``(kept, [(dropped_sentence, reason)])``."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(answer.strip()) if s.strip()]
    texts = [str(sp.get("text", "")) for sp in spans]
    kept: list[str] = []
    dropped: list[tuple[str, str]] = []
    for s in sentences:
        # a summary sentence legitimately draws on several lines ("…, which …; and …"): it is judged clause by clause —
        # each clause must be carried by *one* quoted line (its numbers and ≥2/3 of its words together), different clauses
        # may rest on different lines; the sentence is kept only when every clause is carried (lab after21: the one-span
        # rule per whole sentence rejected every honest three-line synthesis)
        clauses, mentions = _clauses(plan, s)
        reasons: list[str] = []
        for c, content, nums in clauses:
            if not content and not nums:
                continue
            if not texts:
                reasons.append("no quoted line")
                continue
            best: tuple[tuple[bool, bool, int], int, int, bool] | None = None
            for t in texts:
                hay = t.replace(",", ".").replace("\u00a0", " ")
                hay_nums = set(re.findall(r"\d+(?:\.\d+)*", hay))
                nums_ok = all(x in hay_nums or any(h.endswith("." + x) or h.startswith(x + ".") for h in hay_nums) for x in nums)
                hit = sum(1 for w in content if mentions(t, w))
                need = -(-2 * len(content) // 3)   # ceil(2/3 · n); 0 when there are no content words
                score = (nums_ok and hit >= need, nums_ok, hit)
                if best is None or score > best[0]:
                    best = (score, hit, need, nums_ok)
            assert best is not None
            (ok, _n, _h), hit, need, nums_ok = best
            if ok:
                continue
            why = []
            if not nums_ok:
                why.append("its number(s) " + ", ".join(nums) + " are not on one quoted line")
            if hit < need:
                why.append(f"{hit}/{len(content)} of its content words are on the best quoted line (needs {need})")
            where = f"clause '{c[:60]}{'…' if len(c) > 60 else ''}': " if len(clauses) > 1 else ""
            reasons.append(where + ("; ".join(why) or "not carried"))
        if reasons:
            dropped.append((s, " | ".join(reasons)))
        else:
            kept.append(s)
    return kept, dropped


_CLAUSE_SPLIT_RE = re.compile(r";\s+|,\s+(?=(?:which|but|while|whereas|although|and|so|yet|with|stating|noting|showing|including)\b)|\s+[—–]\s+", re.I)


def _clauses(plan: Plan, sentence: str) -> tuple[list[tuple[str, list[str], list[str]]], Callable[[str, str], bool]]:
    """Split a sentence into clauses at `;`, ` — ` and `, which|but|while|and…`; a piece with fewer than three content
    words is merged back into its predecessor so "…, and 2 negation inversions" stays with its sentence. Returns
    ``([(clause, content_words, numbers)], mentions)`` — the sentence's alias-aware ``mentions(text, word)`` test."""
    content_all, mentions, _anchors = _content_terms(plan, sentence, keep_file_words=True)
    allowed = {retrieval.fold(w) for w in content_all if len(w) >= 3 and retrieval.fold(w) not in lexicon.SHAPE_WORDS}

    def words_of(piece: str) -> list[str]:
        return [w for w in dict.fromkeys(retrieval.fold(x) for x in re.findall(r"\w+", retrieval.norm(piece))) if w in allowed]

    pieces = [p.strip() for p in _CLAUSE_SPLIT_RE.split(sentence) if p and p.strip()]
    out: list[tuple[str, list[str], list[str]]] = []
    for p in pieces:
        cw, nums = words_of(p), [x.replace(",", ".") for x in _ANSWER_NUM_RE.findall(p)]
        if out and len(cw) < 3:
            pc, pw, pn = out[-1]
            out[-1] = (pc + ", " + p, list(dict.fromkeys(pw + cw)), pn + nums)
        else:
            out.append((p, cw, nums))
    return out, mentions


def _d2_sentence_gate(r: NodeResult, n: Any, plan: Plan, mode: str) -> None:
    kept, dropped = d2_sentence_entailment(plan, r.answer, r.spans)
    r.attempts.append({"d2_entailment": {"mode": mode, "kept": len(kept), "dropped": len(dropped),
                                         "reasons": [why for _s, why in dropped]}})
    if mode != "strict":
        if dropped:
            r.detail += f"; {len(dropped)} of {len(kept) + len(dropped)} sentence(s) not carried by any quoted line (lenient: kept, counted)"
        return
    label = "summary" if n.kind == "summarize" else "recommendation"
    if not dropped:
        r.status = "COMMITTED"
        r.method += "+entailed"
        r.detail = f"quotes verified verbatim; every sentence of the {label} is carried by a quoted line (numbers and ≥2/3 of its content words on the same line)"
        return
    removed = "\n".join(f"- ~~{s}~~ — {why}" for s, why in dropped)
    if kept:
        r.answer = "\n".join(kept) + f"\n\n_{len(dropped)} sentence(s) removed: not carried by any quoted line_\n{removed}"
        r.detail = (f"quotes verified verbatim; {len(kept)} sentence(s) carried by the quoted lines are stated, "
                    f"{len(dropped)} removed and listed")
    elif n.kind == "summarize" and any(sp.get("text", "").strip() for sp in r.spans):
        # every sentence pruned (live M01 G1R3E after03, 2026-11-06): the quoted lines are verified text of the package —
        # they are stated verbatim as the package's own words, the model's sentences listed as removed; nothing generated
        shown = list(dict.fromkeys((sp["path"], sp["line"], sp["text"].strip()) for sp in r.spans if sp.get("text", "").strip()))[:6]
        r.answer = ("None of the model's sentences is carried by a quoted line; the lines it quoted, verbatim:\n"
                    + "\n".join(f"- `{p}:{ln}` — {_line_statement(t) or t[:300]}" for p, ln, t in shown)
                    + f"\n\n_{len(dropped)} sentence(s) removed: not carried by any quoted line_\n{removed}")
        r.detail = f"quotes verified verbatim; no sentence of the {label} is carried by a quoted line — the quoted lines are shown verbatim, nothing generated"
    else:
        r.answer = f"Nothing is claimed: none of the model's {len(dropped)} sentence(s) is carried by a quoted line.\n{removed}"
        r.detail = f"quotes verified verbatim; no sentence of the {label} is carried by a quoted line — nothing is claimed"
    r.method += "+entailment_pruned"


async def run_compare_sides(r: NodeResult, n: Any, sides: list[NodeResult], call_llm: LlmCall | None, budget: Budget, calls: Calls) -> None:
    """D1 compare over side-lookup nodes: one Q2 call over the sides' verified spans (round-robin), one bounded complement
    call when only one side was quoted. COMMITTED only when every side is quoted."""
    r.route = "D1"
    if any(s.status != "COMMITTED" for s in sides):
        r.status, r.detail = "FAILED", n.failure
        return
    if call_llm is None or calls.exhausted:
        r.status, r.detail = "SKIPPED", calls.budget_note()
        return
    # round-robin across sides so a quote-capped model sees every side early
    hits: list[attach.Hit] = []
    for i in range(max(len(s.spans) for s in sides)):
        for side in sides:
            if i < len(side.spans):
                hits.append(attach.Hit(side.spans[i]["path"], side.spans[i]["line"], side.spans[i]["text"], 1.0))
    hits = hits[:8]
    dec, r.attempts = await q2_decide(call_llm, n.query, hits, max_attempts=budget.max_attempts)
    calls.charge(r.attempts)
    r.model_calls = len(r.attempts)
    if dec is None or not dec["quotes"]:
        r.status, r.detail = "FAILED", "no verified quotes from both sides; verdict undetermined (never guessed)"
        return
    quotes = list(dec["quotes"])
    cited = {q["path"] for q in quotes}
    missing = [side for side in sides if not any(s["path"] in cited for s in side.spans)]
    if missing and not calls.exhausted:
        # one bounded complement call over the unquoted side(s) only (live finding 2026-11-05: the 2B model
        # quotes a single side even when every side is in its excerpts)
        other = [attach.Hit(s["path"], s["line"], s["text"], 1.0) for side in missing for s in side.spans][:8]
        dec2, att2 = await q2_decide(call_llm, n.query, other, max_attempts=1)
        calls.charge(att2)
        r.model_calls += len(att2)
        r.attempts = r.attempts + att2
        if dec2 and dec2["quotes"]:
            quotes += dec2["quotes"]
            cited = {q["path"] for q in quotes}
    both = all(any(s["path"] in cited for s in side.spans) for side in sides)
    r.status = "COMMITTED" if both else "PARTIAL"
    r.method, r.answer, r.spans = "q2_verified_quotes", dec["answer"], spans_of(hits, quotes)
    r.detail = ("second side quoted in a complement call" if both and len(r.attempts) > 1 else "") if both else "only one side is quoted; the other side is unverified"


async def run_d1(r: NodeResult, n: Any, e: dict[str, Any], plan: Plan, call_llm: LlmCall | None, budget: Budget, calls: Calls) -> None:
    """D1 over map-verified excerpts: the Q2 call, then the escalation ladder — not-found coverage retry, off-topic
    quote retry, compare complement, number entailment, polar completion. The entry's status is already FOUND with spans."""
    if call_llm is None or calls.exhausted:
        r.status, r.detail = "SKIPPED", calls.budget_note()
        r.spans = [{"path": s["path"], "line": s["line"], "text": "", "seg_id": s["seg_id"]} for s in e["spans"]]
        return
    hits = hits_from_spans(plan, e, question=n.query)
    r.route = "D1"
    dec, r.attempts = await q2_decide(call_llm, n.query, hits, max_attempts=budget.max_attempts)
    calls.charge(r.attempts)
    r.model_calls = len(r.attempts)
    if dec is None:
        r.status, r.detail = "FAILED", f"{len(r.attempts)} attempt(s) rejected: " + str(r.attempts[-1].get("failure") if r.attempts else "none")
    elif not dec["quotes"]:
        await _not_found_retry(r, n, plan, hits, dec, call_llm, calls)
    else:
        r.status, r.method, r.answer, r.spans = "COMMITTED", "q2_verified_quotes", dec["answer"], spans_of(hits, dec["quotes"])
        gap, on_topic = quote_relevance(plan, n.query, dec["quotes"], hits)
        if gap:
            await _off_topic_retry(r, n, plan, gap, on_topic, hits, call_llm, calls)
        # Measured and reverted (lab 2026-11-06, G1R3E round 1): a "coverage-dominance" retry that re-asked whenever the
        # first quote carried fewer question words than other excerpts replaced three right answers on the K set
        # (K17, K39, K45 — a terse right line lost to wordier wrong ones) and fixed none of M14/M29. A verified
        # quote that is on topic stands; wordiness is not evidence.
    if r.status == "COMMITTED" and r.method.startswith("q2_") and r.method != "q2_not_in_excerpts":
        _which_file_completion(r, n, plan)
        _adjacent_number_check(r, n, plan)
        _number_entailment(r, n, plan, hits)
        _bare_number_grounding(r, n, plan)
        if r.status == "COMMITTED":
            _pointer_answer_check(r, n)
        if r.status == "COMMITTED" and n.kind != "verify":   # a polar node's empty sentence is read by _polar_line_read
            _empty_answer_check(r)
        if r.status == "COMMITTED":
            _why_row_cause(r, n, plan)
    if n.kind == "compare" and dec and dec["quotes"] and r.method == "q2_verified_quotes" and r.status == "COMMITTED":
        # after the sentence checks: they judge the model's first sentence, not the second side's addendum
        sides, missing = compare_missing_side(n, plan, dec["quotes"], hits)
        if missing or len({(q["path"], q["line"]) for q in dec["quotes"]}) < 2:
            await _compare_complement(r, n, dec, hits, call_llm, calls, sides, missing)
    if n.kind == "verify" and r.status in ("COMMITTED", "PARTIAL") and r.method.startswith("q2_") and r.method != "q2_not_in_excerpts":
        _polar_line_read(r, n, plan)
        _polar_qualification(r, n, plan, hits)
        _polar_completion(r, n, plan, hits)
    if r.spans and r.status in ("COMMITTED", "PARTIAL") and "not_in_excerpts" not in (r.method or "") and "Not found" not in (r.answer or ""):
        _cite_equivalents(r, n, plan, hits)


_WHEN_RE = re.compile(r"\b(when|which month|what month|which date|what date|which version|what version)\b", re.I)
_DATE_IN_HEAD_RE = re.compile(r"\b(?:19|20)\d{2}-\d{2}|\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\b", re.I)
_VER_RE = re.compile(r"\d+\.\d+(?:\.\d+)?")


def _cite_equivalents(r: NodeResult, n: Any, plan: Plan, hits: list[attach.Hit]) -> None:
    """The committed line states the fact; the gold also marks the heading above it and the other lines that state the
    same value (oracle C038/C126: the config port is quoted, `README.md` "Use port 18473 for the health endpoint" is
    not; C055/C120: the bullet is quoted, the version heading that dates it is not; C018: a summary quotes one changelog
    line). Retrieved lines only. An untrusted-instruction line is never added. At most eight extra citations."""
    rows = list(getattr(getattr(plan, "retriever", None), "rows", []) or [])
    by_loc = {(row.path, row.line): row for row in rows}
    cited = {(sp["path"], sp["line"]) for sp in r.spans}
    added = 0

    def add(path: str, line: int) -> None:
        nonlocal added
        if added >= 8 or (path, line) in cited:
            return
        row = by_loc.get((path, line))
        text = row.text if row is not None else ""
        if text and scan_text(text):
            return
        r.spans.append({"path": path, "line": line, "text": text, "seg_id": getattr(row, "seg_id", "") if row is not None else ""})
        cited.add((path, line))
        added += 1

    query = getattr(n, "query", "") or ""
    content, mentions, _anchors = _content_terms(plan, query, keep_file_words=True) if query else ([], lambda *_: False, [])
    pool = rows or list(hits)
    num_lines: dict[str, list] = {}
    for row in pool:
        text = getattr(row, "text", "") or ""
        for num in set(re.findall(r"\d{3,}", text)):
            num_lines.setdefault(num, []).append(row)
    quoted_nums: set[str] = set()
    for sp in list(r.spans):
        text = sp.get("text") or getattr(by_loc.get((sp["path"], sp["line"])), "text", "")
        quoted_nums.update(re.findall(r"\d{3,}", text or ""))
    for num in quoted_nums:
        lines = num_lines.get(num) or []
        if len(lines) > 8:
            continue
        for row in lines:
            if any(mentions(row.text, t) for t in content):
                add(row.path, row.line)
    want_when = bool(_WHEN_RE.search(query))
    versions = set(_VER_RE.findall(query))
    for sp in list(r.spans):
        row = by_loc.get((sp["path"], sp["line"]))
        if row is None or not row.heading_line:
            continue
        head = by_loc.get((row.path, row.heading_line))
        if head is None:
            continue
        shares_version = any(v in head.text for v in versions)
        if shares_version or (want_when and _DATE_IN_HEAD_RE.search(head.text)):
            add(head.path, head.line)
        if row.text.lstrip().startswith("#"):
            under = [o for o in pool if o.path == row.path and row.line < o.line <= row.line + 2]
            if under:
                nxt = min(under, key=lambda o: o.line)
                if any(mentions(nxt.text, t) for t in content):
                    add(nxt.path, nxt.line)
    for ver in versions:
        for row in pool:
            if ver in getattr(row, "text", "") and getattr(row, "text", "").lstrip().startswith("#"):
                add(row.path, row.line)
                later = [o for o in pool if o.path == row.path and row.line < o.line <= row.line + 2]
                if later:
                    add(min(later, key=lambda o: o.line).path, min(later, key=lambda o: o.line).line)
    if getattr(n, "kind", "") == "summarize":
        qf = retrieval.fold(query)
        for h in hits:
            stem = h.path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            if len(stem) >= 3 and retrieval.fold(stem) in qf:
                add(h.path, h.line)


async def _not_found_retry(r: NodeResult, n: Any, plan: Plan, hits: list[attach.Hit], dec: dict[str, Any], call_llm: LlmCall, calls: Calls) -> None:
    # the legacy contract's honest negative: excerpts were verified, the model found no answer in them
    r.status, r.method, r.detail = "COMMITTED", "q2_not_in_excerpts", "NOT_FOUND_IN_EXCERPTS"
    r.answer = (f"**Not found in the attached archive(s)** — not in the {len(hits)} retrieved excerpt(s): the model reported no answer there and quoted nothing, so no claim is made."
                + (f" Model note: {dec['answer']}" if dec.get("answer") else ""))
    r.spans = [{"path": h.path, "line": h.line, "text": "", "seg_id": ""} for h in hits[:8]]
    # escalation (Phase 3): a "not found" is not accepted at once when an excerpt in front of the model
    # carries at least half of the question's content words (live K27 2026-11-06: `effect projection may
    # be consumed in shadow/read-only mode` was excerpt 1 and the model answered `found: false`, "No").
    # One bounded re-ask over exactly the covering lines, with the directive at the end of the user turn;
    # its quote is verified verbatim like any other. No quote the second time → the negative stands.
    covering, content = covering_excerpts(plan, n.query, hits)
    if not covering or calls.exhausted:
        return
    top = covering[:6]
    tail = attach.COVERAGE_TAIL.format(
        lines=", ".join(f"{h.path}:{h.line}" for h, _c in top[:3]),
        words=", ".join(dict.fromkeys(w for _h, c in top for w in c))[:160])
    dec2, att2 = await q2_decide(call_llm, n.query, [h for h, _c in top], max_attempts=1, user_tail=tail)
    calls.charge(att2)
    r.model_calls += len(att2)
    r.attempts = r.attempts + att2
    if dec2 and dec2["quotes"] and _VALUE_Q_RE.search(n.query) and not _VALUE_TOKEN_RE.search(dec2["answer"] or ""):
        # "What is the production database password?" re-asked over the convention row that *mentions* rotating a
        # password (live L32 G1R3D, 2026-11-06): the reply "rotate a password" quotes the line but names no value. A
        # question for a credential / identifier / address is answered by a value token or not at all — the negative stands.
        r.detail = (f"NOT_FOUND_IN_EXCERPTS; re-asked once over the {len(top)} excerpt(s) carrying most of the question's words — the reply "
                    f"({(dec2['answer'] or '')[:60]!r}) quotes the line but carries no value, so the negative stands")
        r.answer += " Re-asked once over the most relevant excerpt(s); the reply named no value, so no claim is made."
    elif dec2 and dec2["quotes"]:
        r.method, r.answer, r.spans = "q2_coverage_retry", dec2["answer"], spans_of(hits, dec2["quotes"])
        r.detail = (f"first reply found nothing although {len(covering)} excerpt(s) carried {len(top[0][1])}/{len(content)} of the "
                    f"question's words; re-asked over those lines only")
    else:
        r.detail = (f"NOT_FOUND_IN_EXCERPTS; re-asked once over the {len(top)} excerpt(s) carrying most of the question's words "
                    f"({', '.join(top[0][1][:4])}) — still no quote, so the negative stands")
        r.answer += f" Re-asked once over the {len(top)} most relevant excerpt(s); the model again quoted nothing."
        if n.kind == "verify":
            _covering_read(r, n, top)


_VALUE_Q_RE = re.compile(r"^\s*(what|which)\s+(is|was|are|were)\s+(the\s+)?(\w+[\s-]+){0,4}(password|passphrase|secret|token|api key|key|credential|hash|sha\d*|checksum|commit|version|port|url|uri|endpoint|address|hostname|host|id|identifier|path|filename|email|phone|number|count|value|threshold|date|time)\b", re.I)
_VALUE_TOKEN_RE = re.compile(r"\d|[A-Za-z0-9]+[/._:@-][A-Za-z0-9]|\b[A-Z][A-Z0-9_]{2,}\b|`[^`]+`")   # a digit, a path/host/version-like token, an ALL_CAPS code, or a code span


def _covering_read(r: NodeResult, n: Any, top: list[tuple[attach.Hit, list[str]]]) -> None:
    # a yes/no question the model would not ground twice (live K27 lab after24 2026-11-06: `found: false` with the note
    # "No, … cannot be consumed in shadow now", then no quote over the 3 covering lines either) while the covering lines
    # themselves state a permission or restriction on the question's terms (`may be consumed in shadow/read-only mode`,
    # `may be logged in shadow … provided no decision`). The lane does not keep the model's ungrounded "No": it states those
    # lines verbatim as what the package says, PARTIAL — a deterministic read of verified text, not a model claim.
    lines = [h for h, _c in top if _PERMISSIVE_RE.search(h.text) or _RESTRICTIVE_RE.search(h.text)][:2]
    if not lines:
        return
    r.status, r.method = "PARTIAL", "q2_not_in_excerpts+covering_read"
    r.answer = ("**The model gave no grounded answer** (it quoted nothing twice; its ungrounded note is not committed). What the package "
                "states on the question's terms, verbatim:\n" + "\n".join(f"- `{h.path}:{h.line}` — {h.text.strip()[:300]}" for h in lines))
    r.spans = [{"path": h.path, "line": h.line, "text": h.text, "seg_id": ""} for h in lines]
    r.detail = (r.detail or "") + f"; {len(lines)} covering line(s) stated verbatim instead"


async def _off_topic_retry(r: NodeResult, n: Any, plan: Plan, gap: str, on_topic: list[attach.Hit], hits: list[attach.Hit],
                           call_llm: LlmCall, calls: Calls) -> None:
    # the model quoted a bare title although an excerpt sharing the question's term was in front of it
    # (live 2026-11-05/06, Granite `on`: "quote its exact sentinel" → the README title). One bounded
    # re-ask over *only* the on-topic excerpts; its quote is verified verbatim like any other, and the
    # off-topic first quote is dropped. No usable second quote → PARTIAL with the guard's explanation.
    dec2, att2 = (None, [])
    if on_topic and not calls.exhausted:
        dec2, att2 = await q2_decide(call_llm, n.query, on_topic[:8], max_attempts=1)
        calls.charge(att2)
        r.model_calls += len(att2)
        r.attempts = r.attempts + att2
    if dec2 and dec2["quotes"] and not quote_relevance_gap(plan, n.query, dec2["quotes"], on_topic):
        r.method, r.answer, r.spans = "q2_on_topic_retry", dec2["answer"], spans_of(hits, dec2["quotes"])
        r.detail = "first quote was an off-topic title; re-asked over the on-topic excerpt(s) only"
    else:
        r.status, r.detail = "PARTIAL", gap


Side = tuple[str, Callable[[attach.Hit], bool]]   # (label, membership test over a hit's text / heading / path)
_BETWEEN_RE = re.compile(r"\bbetween\s+(.+?)\s+and\s+(.+?)\s*[?.!]*\s*$", re.I)
_VERSUS_RE = re.compile(r"(\S.*?)\s+(?:vs\.?|versus)\s+(.+?)\s*[?.!]*\s*$", re.I)
_RELATE_RE = re.compile(r"^\s*(?:compare|relate|reconcile|contrast|match|cross-check)\s+(.+?)\s+(?:with|to|and|against)\s+(.+?)\s*[?.!]*\s*$", re.I)
_SIDE_STOP = frozenset({"the", "a", "an", "of", "in", "on", "about", "for", "from", "this", "that", "these", "those", "its", "their", "run", "re", "side"})


def compare_sides(n: Any, plan: Plan) -> list[Side]:
    """The two sides a compare node is about. Named files first (two scope or focus files → each side is a file), else the
    question's own pair (`between A and B`, `A vs B`, `compare/relate A with/to B`): a hit belongs to a phrase side when
    its text or its section heading carries one of the phrase's content words (`1.1.0` labels the bullets under the
    `## 1.1.0` heading). Empty when the node names no pair."""
    files = list(n.source_scope.get("files") or []) or list(n.source_scope.get("focus") or [])
    if len(files) >= 2:
        return [(f, (lambda h, f=f: h.path == f or h.path.endswith("/" + f))) for f in files[:2]]
    m = _BETWEEN_RE.search(n.query) or _VERSUS_RE.search(n.query) or _RELATE_RE.search(n.query)
    if not m:
        return []
    headings = _heading_ancestry(plan)
    sides: list[Side] = []
    for phrase in (m.group(1), m.group(2)):
        words = [w for w in re.findall(r"[\w.\-]+", phrase.lower()) if w.strip(".-") and w not in _SIDE_STOP]
        if not words:
            return []
        toks = [retrieval.fold(w) for w in words]

        def member(h: attach.Hit, toks: list[str] = toks) -> bool:
            text = retrieval.fold(retrieval.norm(h.text)) + " " + headings.get((h.path, h.line), "") + " " + retrieval.fold(h.path)
            return any(re.search(r"(?<![\w.])" + re.escape(t) + r"(?![\w.])", text) for t in toks)
        sides.append((phrase.strip(" `'\""), member))
    a, b = sides
    if a[0].lower() == b[0].lower():
        return []
    return sides


def compare_missing_side(n: Any, plan: Plan, quotes: list[dict[str, Any]], hits: list[attach.Hit]) -> tuple[list[Side], Side | None]:
    """``(sides, missing)`` — the side none of the verified quotes belongs to, when exactly one side is uncovered (both
    covered → complete; neither recognisable among the quotes → no side information, the two-locations rule decides)."""
    sides = compare_sides(n, plan)
    if len(sides) != 2:
        return sides, None
    quoted_at = {(q["path"], q["line"]) for q in quotes}
    quoted_hits = [h for h in hits if (h.path, h.line) in quoted_at]
    covered = [label for label, member in sides if any(member(h) for h in quoted_hits)]
    missing = [s for s in sides if s[0] not in covered]
    return sides, (missing[0] if len(missing) == 1 else None)


async def _compare_complement(r: NodeResult, n: Any, dec: dict[str, Any], hits: list[attach.Hit], call_llm: LlmCall, calls: Calls,
                              sides: list[Side], missing: Side | None) -> None:
    # a comparison with one quoted side is a guess about the other (live finding 2026-11-05: "Yes" citing
    # example.py only; oracle C063/C065 2026-11-06: two quotes, both from the 1.2.0 side / both from results.csv).
    # One bounded complement call asks for the *missing* side by name over the excerpts that belong to it
    # (all remaining excerpts when the sides are not recognisable); the verdict stays the first answer's,
    # the second side's sentence is appended, both rest on verified lines. No second quote: PARTIAL when the
    # first side is a single line; otherwise the answer stands on its lines and the missing side's excerpts
    # are shown unquoted, named as the side the model did not read.
    quoted = {(q["path"], q["line"]) for q in dec["quotes"]}
    remaining = [h for h in hits if (h.path, h.line) not in quoted]
    other = [h for h in remaining if missing[1](h)] if missing else []
    other = other or remaining
    tail = None
    if missing:
        first = next((label for label, _m in sides if label != missing[0]), "the first")
        tail = (f"The question compares {first} with {missing[0]}; the answer so far quotes only the {first} side. "
                f"Quote the line(s) about {missing[0]} from these excerpts, or keep \"found\" false.")
    dec2, att2 = (None, [])
    if other and not calls.exhausted:
        dec2, att2 = await q2_decide(call_llm, n.query, other[:8], max_attempts=1, user_tail=tail)
        calls.charge(att2)
        r.model_calls += len(att2)
        r.attempts = r.attempts + att2
    if dec2 and dec2["quotes"]:
        r.spans = spans_of(hits, dec["quotes"] + dec2["quotes"])
        r.detail = f"second side ({missing[0]}) quoted in a complement call" if missing else "second side quoted in a complement call over the remaining excerpts"
        second = (dec2.get("answer") or "").strip()
        if missing and second and second not in (r.answer or "") and not numbers_not_in_quotes(second, [q["text"] for q in dec2["quotes"]]):
            r.answer = (r.answer or "") + f"\n\n**{missing[0]} side** (complement call, verified quote): {second}"
    elif len(quoted) < 2 or not missing:
        r.status, r.detail = "PARTIAL", "compare: only one side is quoted; the verdict is not committed"
    else:
        r.detail = f"compare: only the {first} side is quoted; the {missing[0]} side was re-asked and not quoted"
        shown = [h for h in remaining if missing[1](h)][:2]
        if shown:
            r.answer = (r.answer or "") + f"\n\nAlso in the excerpts ({missing[0]} side), not quoted by the model:\n" + "\n".join(
                f"- `{h.path}:{h.line}` — {h.text.strip()[:240]}" for h in shown)


_WHICH_FILE_Q_RE = re.compile(r"^\s*(?:which|what)\s+(?:\w+\s+){0,2}files?\b|\bwhich files?\b|\bin which files?\b|\bwhat files?\b", re.I)


def _which_file_completion(r: NodeResult, n: Any, plan: Plan) -> None:
    # "Which file contains the machine-readable results?" (live K31 2026-11-06): the model quoted the README row that names
    # `g1r3a_summary.json`, `g1r3a_gates.csv` and answered "README.md" — the file the quote lives in, not the files the
    # line names. When a which-file question's verified quote names attached files other than its own, those names are
    # the answer and are read from the line; the model's sentence is kept only when it already names one of them.
    if not _WHICH_FILE_Q_RE.search(n.query):
        return
    paths = [f.path for f in plan.amap.files]
    quoted = " ".join(str(sp.get("text", "")) for sp in r.spans)
    own = {sp.get("path") for sp in r.spans}
    named_at: list[tuple[int, str]] = []
    for p in paths:
        base = p.rsplit("/", 1)[-1]
        if p in own or len(base) < 5:
            continue
        m = re.search(r"(?<![\w/.-])" + re.escape(base) + r"(?![\w-])", quoted) or re.search(r"(?<![\w-])" + re.escape(p) + r"(?![\w-])", quoted)
        if m:
            named_at.append((m.start(), p))
    named = [p for _pos, p in sorted(named_at)]   # in the order the line names them
    if not named:
        return
    if any(re.search(r"(?<![\w/.-])" + re.escape(p.rsplit("/", 1)[-1]) + r"(?![\w-])", r.answer) for p in named):
        return
    r.answer = "The quoted line names " + ", ".join(f"`{p}`" for p in named[:6]) + f" (the model's sentence named `{', '.join(sorted(own))}`, the file the line is in; dropped)."
    r.method += "+which_file"
    r.detail = (r.detail + "; " if r.detail else "") + "file names read from the quoted line"


_POINTER_ANSWER_RE = re.compile(r"^[\s`'\"*]*(?:[\w.-]+/)*[\w.-]+\.[A-Za-z][A-Za-z0-9]{0,5}(?::\d+)?[\s`'\"*.]*$")   # `dce-g1r/0.6.1` is a version, not a file (live L16 G1R3D)


_CAUSE_COL_RE = re.compile(r"\b(?:cause|causes|reason|reasons|why|because|rationale|explanation|root)\b", re.I)


def _why_row_cause(r: NodeResult, n: Any, plan: Plan) -> None:
    """A why-question answered from a quoted *table row* that has a cause column (`Root cause`, `Reason`, `Why`): the reason
    is that cell, read deterministically; the model's sentence is kept only when it already says the cell. Live L20 G1R3D
    (lab after07, 2026-11-07): "Why was 'Create a Dockerfile' read as an environment mutation?" quoted the right taxonomy
    row and answered `output_medium` — the row's category, not its `Root cause` cell (`_CONFIG_FILE_RE` treated any
    Dockerfile as a configuration change). One quoted row only; several rows or no cause column leave the sentence alone."""
    if not retrieval._WHY_Q_RE.match(n.query or "") or r.method == "q2_not_in_excerpts":
        return
    keyed = {(sp.get("path"), int(sp.get("line") or 0)) for sp in r.spans}
    if len(keyed) != 1:
        return
    path, line = next(iter(keyed))
    from . import tables
    for t in tables.tables_of(plan.amap):
        if t.path != path:
            continue
        cause_cols = [c for c in t.columns if _CAUSE_COL_RE.search(c)]
        if len(cause_cols) != 1:
            continue
        row = next((rw for rw in t.rows if rw.seg.start_line == line), None)
        if row is None:
            continue
        cell = (row.cells.get(cause_cols[0]) or "").strip()
        if not cell:
            return
        cell_words = {w for w in re.findall(r"[a-z0-9]{3,}", cell.casefold())} - retrieval.STOPWORDS
        ans_words = set(re.findall(r"[a-z0-9]{3,}", str(r.answer or "").casefold()))
        if cell_words and len(cell_words & ans_words) * 2 >= len(cell_words):
            return   # the sentence already states the reason
        said = str(r.answer or "").strip()[:80]
        r.answer = (f"**{cell}** — the `{cause_cols[0]}` cell of the quoted row (`{path}:{line}`)"
                    + (f"; the model's sentence said {said!r}, which is another cell of that row, not the reason." if said else "."))
        r.method += "+row_cause"
        r.detail = (r.detail + "; " if r.detail else "") + f"why-question: the reason is read from the row's `{cause_cols[0]}` cell"
        return


def _pointer_answer_check(r: NodeResult, n: Any) -> None:
    # "Who labelled the blind set?" answered `blind/CONVENTION_SHEET_V2.md:1` (live K16 2026-11-06, after19) — the model's
    # sentence is a file pointer, not what the quoted line says. Unless the question asks for a file, a bare path /
    # `path:line` answer is not committed: the quoted line is shown as the evidence and the status says the sentence
    # carried no answer.
    if _WHICH_FILE_Q_RE.search(n.query) or not _POINTER_ANSWER_RE.match(r.answer or "") or not r.spans:
        return
    if re.search(r"\b(where|which (?:file|path|document)|what file|path|location)\b", n.query, re.I):
        return
    pointer = r.answer.strip().strip("`*\"'.")
    read = _line_statement(r.spans[0].get("text") or "")
    if read and len(r.spans) == 1:
        # the model chose one line and then pointed at it instead of reading it (live K16 2026-11-06, Granite: the coverage
        # retry quoted `04_BLIND_EVALUATION.md:8` — "Blind set authored by a **separate agent session** …" — and the sentence
        # was `blind/CONVENTION_SHEET_V2.md:1`). The line's own statement is shown verbatim as the answer: nothing is
        # generated, the text is the verified excerpt the model selected for the question.
        r.answer = f"From the quoted line, verbatim (the model's sentence was only a file pointer, `{pointer}`): {read}"
        r.method += "+line_read"
        r.detail = (r.detail + "; " if r.detail else "") + "the model's sentence named a file location; the quoted line is shown verbatim instead"
        return
    r.status = "PARTIAL"
    r.answer = f"The quoted line is the evidence; the model's sentence was only a file pointer (`{pointer}`), not an answer, and is not committed."
    r.method += "+pointer_answer"
    r.detail = (r.detail + "; " if r.detail else "") + "the model's sentence names a file location instead of what the line says"


def _empty_answer_check(r: NodeResult) -> None:
    # a salvaged (truncated) reply can verify its quotes and still carry no sentence — live L21 G1R3D after02 (2026-11-06):
    # `answer` "" over four quoted lines, COMMITTED. Nothing was stated, so nothing is committed: one quoted line is read
    # verbatim, several are shown unasserted as PARTIAL.
    if str(r.answer or "").strip() not in ("", "[]", "{}", "None", "null"):
        return
    read = _line_statement(r.spans[0].get("text") or "") if len(r.spans) == 1 else ""
    if read:
        r.answer = f"From the quoted line, verbatim (the model's reply carried no sentence): {read}"
        r.method += "+line_read"
        r.detail = (r.detail + "; " if r.detail else "") + "the model's reply carried no sentence; the quoted line is shown verbatim instead"
        return
    r.status = "PARTIAL"
    r.answer = f"The model's reply carried no sentence (truncated or empty); the {len(r.spans)} quoted line(s) below are the evidence it selected and are shown unasserted."
    r.method += "+empty_answer"
    r.detail = (r.detail + "; " if r.detail else "") + "empty answer over verified quotes is not committed"


def _line_statement(text: str) -> str:
    """The statement a quoted line makes, verbatim: a markdown table row's cells joined with ` — ` (header/separator rows
    give nothing), otherwise the line up to its first two sentences, capped at 300 characters."""
    s = text.strip()
    if not s:
        return ""
    if s.startswith("|"):
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            return ""
        return " — ".join(c for c in cells if c)[:300]
    sentences = re.split(r"(?<=[.!?])\s+", s)
    return " ".join(sentences[:2])[:300]


_HOW_MANY_Q_RE = re.compile(r"^\s*how many\b|\bnumber of\b|\bhow much\b", re.I)
_TOKEN_SEP_RE = re.compile(r"\d+(?:[.,]\d+)*|[^\W\d_]+|[/|;,·•]")


def _adjacent_number_check(r: NodeResult, n: Any, plan: Plan) -> None:
    # "How many blind cases are in Ukrainian?" over `124 cases (70 en / 39 uk / 15 mixed)` — the model said 70 (live K19
    # 2026-11-06); every number is in the line, so number entailment holds and the sentence is still wrong. For a how-many
    # question, the number that sits next to the question's key term in the quoted line — with no list separator
    # (`/`, `,`, `;`, `|`, `·`) between them — is read deterministically; when exactly one such number exists and the
    # answer does not carry it, the answer is replaced by that reading and the node is PARTIAL (adjacency is a reading,
    # not a proof). Terms that are the counted noun itself (`cases`) or occur in every quoted line are not keys.
    if not _HOW_MANY_Q_RE.search(n.query):
        return
    if not re.search(r"\d|\b(?:zero|none|no|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|dozen|all|every)\b", _ANSWER_HASH_RE.sub(" ", str(r.answer or "")), re.I):
        # a how-many question answered without any count ("766cb08" for "How many sealed cases were in the blind set?" —
        # live K42 after30, 2026-11-06): the sentence is not an answer to the question asked
        r.status = "PARTIAL"
        r.method += "+no_count"
        said = str(r.answer or "").strip()[:80]
        r.answer = f"No count is stated: the model's reply ({said!r}) carries no number, so it does not answer the question; the quoted line(s) are shown as the excerpts checked."
        r.detail = (r.detail + "; " if r.detail else "") + "a how-many question was answered without a number; the quoted line(s) are shown, no count is claimed"
        return
    content, mentions, _anchors = _content_terms(plan, n.query, keep_file_words=True)
    if not content:
        return
    texts = [str(sp.get("text", "")) for sp in r.spans if sp.get("text")]
    if not texts:
        return
    found: dict[str, set[str]] = {}
    token_of: dict[str, str] = {}   # question term → the line's word it matched (`ukrainian` → `uk`)
    for text in texts:
        toks = _TOKEN_SEP_RE.findall(text)
        # a line that says only the counted noun (`"cases": 20,` in a dump, live M20 G1R3E 2026-11-06) counts *something*
        # called cases, not what the question asks; the adjacency reading needs the line to carry a second question term
        # (`124 cases (70 en / 39 uk …)` carries `uk` for "blind cases in Ukrainian") unless the question has only one
        line_terms = {t for tok in toks if re.match(r"[^\W\d_]+$", tok) for t in content if mentions(tok, t)}
        if len(line_terms) < min(2, len(content)):
            continue
        for i, tok in enumerate(toks):
            if not re.match(r"[^\W\d_]+$", tok):
                continue
            for t in content:
                if not mentions(tok, t):
                    continue
                for j in (i - 1, i + 1):
                    if 0 <= j < len(toks) and re.match(r"\d", toks[j]):
                        found.setdefault(t, set()).add(toks[j])
                        token_of.setdefault(t, tok)
    # a term found next to a number in one place only is a key; the counted noun (next to the total) usually sits beside
    # a different number, so when two terms disagree the one that is *not* the sentence's first noun wins only if unique
    keys = {t: v for t, v in found.items() if len(v) == 1}
    if not keys:
        return
    if len({next(iter(v)) for v in keys.values()}) != 1:
        # two keys, two numbers ("cases" → 124, "uk" → 39): the more specific key is the last content term of the question
        last = next((t for t in reversed(content) if t in keys), None)
        if last is None:
            return
        keys = {last: keys[last]}
    term, vals = next(iter(keys.items()))
    value = next(iter(vals))
    word = token_of.get(term, term)
    answer_nums = set(re.findall(r"\d+(?:[.,]\d+)*", r.answer))   # `30s`, `18473/tcp` count: the unit is glued to the number (oracle C116)
    if value in answer_nums or value.replace(",", ".") in {a.replace(",", ".") for a in answer_nums}:
        return
    r.status = "PARTIAL"
    r.answer = (f"**{value}** — read from the quoted line, where {value} stands next to '{word}'"
                + (f" (the model's sentence said {', '.join(sorted(answer_nums))}; not carried next to '{word}', dropped)." if answer_nums else "."))
    r.method += "+adjacent_number"
    r.detail = (r.detail + "; " if r.detail else "") + f"the model's number did not match the one next to '{word}' in the quoted line"


_TYPED_VALUE_Q_RE = re.compile(r"^\s*(?:in\s+|at\s+|under\s+)?(?:which|what)\s+(?:is\s+the\s+|was\s+the\s+)?(commit|hash|sha|version|date|port|tag|branch)\b", re.I)


def _typed_value_from_quotes(r: NodeResult, query: str, loose: list[str]) -> bool:
    """A "which commit / version / port …" question whose model value no quoted line carries: the quoted lines are the
    verified evidence, so the value of the asked type they carry is read off them deterministically. Exactly one such
    value → the lane states it (`+typed_value_from_quote`), the model's is named as dropped. Several → all are listed and
    no claim is made. Live K17/K45 G1R3A after31, 2026-11-06: `| Hash-frozen … commit `c181630` |` quoted, the model said
    `097b06a` (the *candidate* freeze on the next row). None → nothing changes (the PARTIAL stands)."""
    m = _TYPED_VALUE_Q_RE.match(query or "")
    if not m:
        return False
    type_word = m.group(1).lower()
    if type_word in ("port", "branch"):
        return False   # any 2–5-digit number / any word would qualify: nothing typed to read
    val_re = re.compile(retrieval.VALUE_RE_FOR[type_word], re.I)
    carried: list[str] = []
    for sp in r.spans:
        for v in val_re.findall(sp.get("text", "")):
            if type_word in ("commit", "hash", "sha") and not (re.search(r"\d", v) and re.search(r"[a-f]", v, re.I)):
                continue   # a hex hash has both digits and letters; a bare integer is not one
            if v not in carried:
                carried.append(v)
    if not carried:
        return False
    said = ", ".join(loose[:3])
    if len(carried) == 1:
        r.status = "COMMITTED"
        r.method += "+typed_value_from_quote"
        r.answer = (f"**{carried[0]}** — the only {type_word} the quoted line(s) carry; the model's sentence said {said}, which no quoted "
                    f"line carries, so it is dropped and the quoted value is stated instead.")
        r.detail = (r.detail + "; " if r.detail else "") + f"the model's {type_word} {said} is in no quoted line; the one {type_word} the quotes carry is stated"
        return True
    r.status = "PARTIAL"
    r.method += "+typed_values_listed"
    r.answer = (f"The quoted line(s) carry {len(carried)} values of type {type_word}: {', '.join(f'`{v}`' for v in carried)}; the model's sentence said "
                f"{said}, which none of them is. Which of the carried values answers the question is not stated — the lines are shown.")
    r.detail = (r.detail + "; " if r.detail else "") + f"the model's {type_word} {said} is in no quoted line; {len(carried)} {type_word} values carried, none claimed"
    return True


def _count_read_from_hits(r: NodeResult, n: Any, plan: Plan, hits: list[attach.Hit], number: str) -> bool:
    """A how-many reply that is only a number no *quoted* line carries, while exactly one indexed line places that
    same number next to a distinguishing word of the question (not the counted noun itself). The model knew the count
    and quoted the wrong line (live K42 G1R3A, 2026-11-07: "124" quoting `blind_sha256_sealed: 90b776ff…` while
    `… on 124 sealed cases` is the only line in the package with 124 next to `sealed`; it was indexed but not in the
    top window. `"cases": 124` does not qualify — `cases` is the counted noun). The scan is over the index, not the
    window, because that is the line the window dropped. Zero or several such lines → the refusal stands. PARTIAL:
    adjacency is a reading, not a proof."""
    from . import tables
    if not _HOW_MANY_Q_RE.search(n.query or "") or not hits:
        return False
    content, mentions, _anchors = _content_terms(plan, n.query, keep_file_words=True)
    keys = [t for t in content if t not in tables._COUNTED_NOUNS and len(t) >= 5]
    if not keys:
        return False
    want = number.replace(",", ".")
    found: list[tuple[str, int, str, str, Any]] = []
    rows = list(getattr(getattr(plan, "retriever", None), "rows", []) or []) or list(hits)
    for h in rows:
        if want not in h.text.replace(",", "."):
            continue
        toks = _TOKEN_SEP_RE.findall(h.text)
        for i, tok in enumerate(toks):
            if not re.match(r"\d", tok) or tok.replace(",", ".") != want:
                continue
            for j in (i - 1, i + 1):
                if not (0 <= j < len(toks) and re.match(r"[^\W\d_]+$", toks[j])):
                    continue
                for t in keys:
                    if mentions(toks[j], t):
                        found.append((h.path, h.line, t, toks[j], h))
    locs = {(p, ln) for p, ln, _t, _w, _h in found}
    if len(locs) != 1:
        return False
    path, line, _term, word, h = found[0]
    r.status = "PARTIAL"
    r.method += "+count_in_excerpt"
    r.answer = (f"**{number}** — read from `{path}:{line}`, where {number} stands next to '{word}'; the model's reply was only this number "
                f"and the line it quoted does not carry it, so the quote is dropped and this reading of the retrieved excerpt is stated.")
    r.spans = [{"path": path, "line": line, "text": h.text, "seg_id": getattr(h, "seg_id", "") or ""}]
    r.detail = (f"the reply was the bare number {number}, carried by no quoted line; exactly one retrieved excerpt places it next to "
                f"'{word}' ({path}:{line})")
    return True


def _bold_count_read(r: NodeResult, n: Any, plan: Plan, hits: list[attach.Hit], number: str) -> bool:
    """A how-many reply that is only a number no quoted line carries, while exactly one indexed line *bolds* a different
    number next to a distinguishing word of the question. The model named the set size; the package states the count
    (live M20 G1R3E: the reply was 184, and `**11 parser faults**` is the only bold count next to `parser`). A number
    that merely sits next to the counted noun is not this reading, and two bold counts keep the refusal. PARTIAL."""
    from . import tables
    if not _HOW_MANY_Q_RE.search(n.query or "") or not hits:
        return False
    content, mentions, _anchors = _content_terms(plan, n.query, keep_file_words=True)
    keys = [t for t in content if t not in tables._COUNTED_NOUNS and len(t) >= 5]
    if not keys:
        return False
    found: list[tuple[str, str, int, str, Any]] = []
    rows = list(getattr(getattr(plan, "retriever", None), "rows", []) or []) or list(hits)
    for h in rows:
        for m in re.finditer(r"\*\*(\d[\d,]*)\s+([^*]+?)\*\*", h.text):
            num, phrase = m.group(1).replace(",", ""), m.group(2)
            for w in re.findall(r"[^\W\d_]+", phrase):
                if any(mentions(w, t) for t in keys):
                    found.append((num, h.path, h.line, w, h))
                    break
    nums = {num for num, _p, _ln, _w, _h in found}
    locs = {(p, ln) for _n, p, ln, _w, _h in found}
    if len(nums) != 1 or len(locs) != 1:
        return False
    stated, path, line, word, h = found[0]
    r.status = "PARTIAL"
    r.method += "+bold_count"
    r.answer = (f"**{stated}** — read from `{path}:{line}`, where the package bolds {stated} next to '{word}'; the model's reply was "
                f"only the number {number}, which that line does not carry, so the quote is dropped and this reading is stated.")
    r.spans = [{"path": path, "line": line, "text": h.text, "seg_id": getattr(h, "seg_id", "") or ""}]
    r.detail = (f"the reply was the bare number {number}, carried by no quoted line; exactly one indexed line bolds {stated} "
                f"next to '{word}' ({path}:{line})")
    return True


def _number_entailment(r: NodeResult, n: Any = None, plan: Plan | None = None, hits: list[attach.Hit] | None = None) -> None:
    # number entailment (Phase 3): a D1 answer may only state numbers its quoted lines carry. Live K13
    # 2026-11-06: the right row was quoted (`0.519 / 0.541 ms`) and the answer said "0.41 ms" — a
    # verified quote does not make the sentence around it true, so the node is PARTIAL and says which
    # number no quoted line carries. The quoted lines stay as the evidence. A bare number on a how-many
    # question is first offered to ``_count_read_from_hits`` (exactly one other excerpt places it next to a
    # distinguishing word); otherwise it is the honest negative.
    query = getattr(n, "query", "") or ""
    loose = numbers_not_in_quotes(r.answer, [sp.get("text", "") for sp in r.spans])
    if loose:
        rest = re.sub(r"[-+]?\d[\d.,/%]*", " ", str(r.answer or ""))
        if not re.search(r"[A-Za-z]{3,}", rest):
            if n is not None and plan is not None and hits and (
                    _count_read_from_hits(r, n, plan, hits, loose[0]) or _bold_count_read(r, n, plan, hits, loose[0])):
                return
            # the sentence *is* the unsupported number ("0.95" for a metric the package never reports — live M35 G1R3E,
            # 2026-11-06): nothing verifiable was stated, so this is the honest negative, with the quoted lines shown as
            # the excerpts that were checked, not as evidence for a value
            r.status, r.method = "COMMITTED", "q2_not_in_excerpts"
            r.answer = (f"**Not found in the attached archive(s)** — the model's reply was only the number {loose[0]}, which none of its quoted "
                        f"line(s) carries; a value no excerpt states is not an answer, so no claim is made.")
            r.detail = f"NOT_FOUND_IN_EXCERPTS; the reply was a bare number ({', '.join(loose[:3])}) carried by no quoted line"
            return
        if _typed_value_from_quotes(r, query, loose):
            return
        r.status = "PARTIAL"
        r.detail = (f"the answer states {', '.join(loose[:3])} which no quoted line carries; the quoted line(s) are the evidence, "
                    f"the number in the sentence is the model's") + (f"; {r.detail}" if r.detail else "")


def _bare_number_grounding(r: NodeResult, n: Any, plan: Plan) -> None:
    # a reply that is only a number, carried by its quoted line, for a question whose qualifiers that line does not carry:
    # "What was the weighted recall on the Ukrainian sealed slice?" → `"flag_recall": 0.961` under `sealed_run.gates`
    # (live M35 G1R3E after02, 2026-11-06 — the package has no Ukrainian slice). The number is real, the line is on
    # topic by one word, and the sentence claims it is the asked value. When the quoted lines — text, key path, heading
    # ancestry and file name together — mention fewer than half of the question's content terms, the number is not shown
    # to be the asked one and the node is the honest negative. A full row or a line under a heading that says the words
    # (`| long_~3000 | 6.359 |` under `parse + projection p50 / p95`) is grounded and untouched.
    if r.status != "COMMITTED" or r.method != "q2_verified_quotes":
        return
    rest = re.sub(r"[-+]?\d[\d.,/%]*", " ", str(r.answer or ""))
    if re.search(r"[A-Za-z]{3,}", rest) or not re.search(r"\d", str(r.answer or "")):
        return
    content, mentions, _anchors = _content_terms(plan, n.query, keep_file_words=True)
    if len(content) < 3:
        return
    quoted = [sp for sp in r.spans if sp.get("text")]
    if not quoted:
        return
    by_loc = {(row.path, row.line): row for row in plan.retriever.rows} if getattr(plan, "retriever", None) is not None else {}
    carried: set[str] = set()
    for sp in quoted:
        row = by_loc.get((sp["path"], sp["line"]))
        texts = [str(sp["text"]), sp["path"].replace("/", " ").replace(".", " ").replace("_", " ")]
        if row is not None:
            texts += [row.heading, " ".join(sorted(row.keys)).replace("_", " ").replace(".", " ")]
        for t in content:
            if any(mentions(tx, t) for tx in texts if tx):
                carried.add(t)
    if len(carried) * 2 >= len(content):
        return
    missing = [t for t in content if t not in carried]
    num = re.search(r"[-+]?\d[\d.,/%]*", str(r.answer)).group(0)
    r.method = "q2_not_in_excerpts"
    r.answer = (f"**Not found in the attached archive(s)** — the model's reply was only the number {num}, read from a line that says nothing of "
                f"{', '.join(f'`{t}`' for t in missing[:4])}; a number whose line does not name what the question asks is not shown to be that value, so no claim is made.")
    r.detail = f"NOT_FOUND_IN_EXCERPTS; bare number {num} from a line carrying {len(carried)} of the question's {len(content)} terms ({', '.join(sorted(carried)) or 'none'})"


_NEGATIVE_ANSWER_RE = re.compile(r"^\W*(no|not|never|none)\b|\b(cannot|can't|can not|is not|isn't|are not|aren't|should not|shouldn't|must not|not yet)\b", re.I)
_POSITIVE_ANSWER_RE = re.compile(r"^\W*(yes|yeah|correct|indeed|true)\b", re.I)
_PERMISSIVE_RE = re.compile(r"(?<!\bnot )(?<!\bnever )(?<!\bno )\b(may|can|could|allowed|permitted|is possible|are possible)\b", re.I)
_RESTRICTIVE_RE = re.compile(r"\b(not|never|until|unless|only|provided (?:that )?|except|hold|cannot|no longer)\b", re.I)


_NEGATOR_RE = re.compile(r"\b(never|not|no|cannot|can't|isn't|aren't|wasn't|weren't|without|neither|nor)\b", re.I)


def _polar_line_read(r: NodeResult, n: Any, plan: Plan) -> None:
    # the model's sentence against its own quoted line (live L18/L19 G1R3D, 2026-11-06): "TEXT_NOT_PROHIBITED is a
    # permission" quoting `TEXT_NOT_PROHIBITED is **never** permission`, and an *empty* sentence quoting `DEFERRED — not
    # removed`. When the single quoted line negates a content word of the question within its clause and the sentence
    # carries no negation (or no words at all), the sentence is not what the line says: the line is stated verbatim as
    # the answer — a deterministic read of verified text; the model's wording is dropped, not corrected.
    quoted = [sp for sp in r.spans if sp.get("text")]
    if len({(sp["path"], sp["line"]) for sp in quoted}) != 1:
        return
    line = quoted[0]["text"].strip()
    answer = (r.answer or "").strip()
    content, mentions, _anchors = _content_terms(plan, n.query)
    if not content:
        return
    folded = retrieval.fold(retrieval.norm(line))
    negated_term = None
    for m in _NEGATOR_RE.finditer(folded):
        window = folded[m.end(): m.end() + 60]
        for t in content:
            if mentions(window, t):
                negated_term = t
                break
        if negated_term:
            break
    if answer and (not negated_term or _NEGATOR_RE.search(answer) or _NEGATIVE_ANSWER_RE.search(answer[:80])):
        return
    if not answer and not negated_term and not _PERMISSIVE_RE.search(line) and not _RESTRICTIVE_RE.search(line):
        return
    read = _line_statement(line)
    if not read:
        return
    why = ("the model's sentence affirmed what the quoted line denies" if answer else "the model's sentence was empty")
    r.answer = f"From the quoted line, verbatim ({why}): {read}"
    r.method += "+line_read"
    r.detail = (r.detail + "; " if r.detail else "") + why + "; the line is stated instead"


def _polar_qualification(r: NodeResult, n: Any, plan: Plan, hits: list[attach.Hit]) -> None:
    # two-way answer guard: a bare "No" (or "Yes") whose other side is written in a covering excerpt the model did not
    # quote — live K27 2026-11-06 (lab and Granite): "No, the effect projection cannot be consumed in shadow now" citing
    # `Decision: HOLD`, while `may be **logged in shadow** … provided no decision … derives from them` and the gate
    # definition `"effect projection may be consumed in shadow/read-only mode"` were in front of the model. A negative
    # answer is qualified by covering lines that permit (`may`, `can`, `allowed`), a positive one by lines that restrict
    # (`not`, `until`, `only`, `provided`). The lines are stated verbatim as the answer's other side — the node becomes
    # PARTIAL: the model's sentence is one-sided, the package is not. Nothing is generated.
    answer = (r.answer or "").strip()
    if _NEGATIVE_ANSWER_RE.search(answer[:80]):
        other = _PERMISSIVE_RE
    elif _POSITIVE_ANSWER_RE.search(answer[:20]):
        other = _RESTRICTIVE_RE
    else:
        return
    quoted_at = {(sp["path"], sp["line"]) for sp in r.spans}
    covering, _content = covering_excerpts(plan, n.query, hits)
    qualifying = [h for h, _c in covering if (h.path, h.line) not in quoted_at and other.search(h.text)][:2]
    if not qualifying:
        return
    side = "permit" if other is _PERMISSIVE_RE else "restrict"
    r.status = "PARTIAL"
    r.answer = (answer + f"\n\n**Qualified by the package** — the model's answer is one-sided; the following verified line(s) {side} what it "
                + ("denies" if side == "permit" else "affirms") + ", stated verbatim:\n"
                + "\n".join(f"- `{h.path}:{h.line}` — {h.text.strip()[:300]}" for h in qualifying))
    r.spans = r.spans + [{"path": h.path, "line": h.line, "text": h.text, "seg_id": ""} for h in qualifying]
    r.method += "+qualified"
    r.detail = (r.detail + "; " if r.detail else "") + f"polar answer qualified by {len(qualifying)} covering line(s) stating the other side"


def _polar_completion(r: NodeResult, n: Any, plan: Plan, hits: list[attach.Hit]) -> None:
    # polar completion (Phase 3): a yes/no answer rests on the line the model chose, but the package may
    # say more — live K27 2026-11-06: "No" citing `Decision: HOLD … not recommended until G1R3B` while
    # `may be logged in shadow (read-only, no decisions)` and the gate definition were in the excerpts.
    # Every other excerpt that carries most of the question's words is shown under the answer, marked
    # as not quoted by the model: the reader sees the qualification, nothing is claimed from it.
    quoted_at = {(sp["path"], sp["line"]) for sp in r.spans}
    covering, _content = covering_excerpts(plan, n.query, hits)
    extra = [h for h, _c in covering if (h.path, h.line) not in quoted_at][:2]
    if extra:
        r.answer += "\n\nAlso in the excerpts, not quoted by the model:\n" + "\n".join(f"- `{h.path}:{h.line}` — {h.text.strip()[:240]}" for h in extra)
        r.detail = (r.detail + "; " if r.detail else "") + f"{len(extra)} further covering line(s) shown unquoted"
