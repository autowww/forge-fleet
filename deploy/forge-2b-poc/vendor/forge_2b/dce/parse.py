"""DCE-01: deterministic request comprehension — ``parse_request(text, attached_refs) -> RequestIR``.

Pure Python regex rules (see ``lexicon.py``); no models, no network, no archive *content* is ever read here — only
attachment names/paths may be passed in, and they can only ever *resolve* a mention the user wrote, never create a goal.

Pipeline: hash → language hint → housekeeping gate → sentence spans → sentence-level constraints (negation/exclusion
masks) → clause split on sequence/coordination markers → one operator per clause by lexicon priority → targets resolved
against attached file names → ellipsis/pronoun merges → unresolved ledger for every clause that produced nothing →
deterministic route + rationale. Every emitted span is a slice of the original prompt.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from . import lexicon as L
from .ir import (IR_VERSION, Ambiguity, AttachmentRef, Constraint, Goal, RequestIR, Routing, Span, Target, Unresolved, prompt_hash)

_WORD_RE = re.compile(r"[\w'\u00c0-\u024f\u0400-\u04ff-]+", re.U)
_PRONOUN_ONLY_RE = re.compile(r"^\s*(it|them|this|that|those|these|both|each|all|him|her)\s*[.!?]*\s*$", re.I)
_WH_START_RE = re.compile(r"^\s*(what|which|who|when|where|why|how|is|are|does|do|did|was|were|can|could|whats)\b", re.I)
_TRAIL_PUNCT = " \t\n,;:.!?—-"


# --- helpers --------------------------------------------------------------------------------------------------------

def _span(text: str, start: int, end: int) -> Span:
    # trim whitespace/punctuation at both ends but keep offsets honest
    while start < end and text[start] in " \t\n":
        start += 1
    while end > start and text[end - 1] in _TRAIL_PUNCT:
        end -= 1
    return Span(start, end, text[start:end])


def _language_hint(text: str) -> str:
    if L.CYRILLIC_RE.search(text):
        for code in ("uk", "ru"):
            pat = dict(L.LANG_HINTS)[code]
            if pat.search(text):
                return code
        return "ru"
    best, score = "en", 0
    for code, pat in L.LANG_HINTS:
        if code in ("uk", "ru"):
            continue
        n = len(pat.findall(text))
        if n > score:
            best, score = code, n
    return best if score >= 2 else "en"


def _norm_refs(attached_refs: Iterable[Any] | None) -> list[AttachmentRef]:
    out: list[AttachmentRef] = []
    for r in attached_refs or []:
        if isinstance(r, AttachmentRef):
            out.append(AttachmentRef(r.name, r.kind, sorted(r.files)))
        else:
            kind = str(r.get("kind", "text"))
            files = list(r.get("files") or ([r["name"]] if kind == "text" else []))
            out.append(AttachmentRef(str(r["name"]), kind if kind in ("zip", "text") else "text", sorted(map(str, files))))
    return out


class _Aliases:
    """Attached file names → lookup tables. Built from names only; never from content."""

    def __init__(self, refs: list[AttachmentRef]):
        self.files: list[str] = sorted({f for r in refs for f in r.files})
        self.by_alias: dict[str, set[str]] = {}
        self.by_ext: dict[str, set[str]] = {}
        for f in self.files:
            low = f.lower()
            base = low.rsplit("/", 1)[-1]
            stem, _, ext = base.rpartition(".")
            if not stem:
                stem, ext = base, ""
            self.by_ext.setdefault(ext, set()).add(f)
            for a in {low, base, stem}:
                self.by_alias.setdefault(a, set()).add(f)
            for tok in re.split(r"[-_.]+", stem):
                if len(tok) >= 4 and tok not in L.GENERIC_BASENAMES:
                    self.by_alias.setdefault(tok, set()).add(f)
            for d in low.split("/")[:-1]:
                if len(d) >= 3:
                    self.by_alias.setdefault(d, set()).add(f)

    def resolve_path(self, mention: str) -> list[str]:
        m = mention.lower().lstrip("./")
        return [f for f in self.files if f.lower() == m or f.lower().endswith("/" + m) or f.lower().rsplit("/", 1)[-1] == m.rsplit("/", 1)[-1]]


# --- main ---------------------------------------------------------------------------------------------------------

def parse_request(text: str, attached_refs: Iterable[Any] | None = None, *, reference_time: str | None = None, locale: str = "en") -> RequestIR:
    """Parse one user request into RequestIR v1. ``reference_time`` is recorded for time constraints but never used to
    resolve relative dates silently (DCE-01 has no date resolver); ``locale`` is informational."""
    refs = _norm_refs(attached_refs)
    aliases = _Aliases(refs)
    ir = RequestIR(version=IR_VERSION, prompt_sha256=prompt_hash(text), text=text, language_hint=_language_hint(text), goals=[],
                   constraints=[], attachments=refs, unresolved=[], ambiguities=[], smalltalk=[], premises=[],
                   routing=Routing("unsupported"), coverage={"clauses": 0, "clauses_with_goal": 0, "unresolved_clauses": 0, "chars_covered": 0, "chars_total": len(text.strip())})
    if L.TASK_PREAMBLE_RE.search(text):
        ir.routing = Routing("housekeeping", ["prompt starts with '### Task:' — Open WebUI housekeeping, answered zero-model"], False)
        ir.coverage.update(clauses=1, chars_covered=len(text.strip()))
        ir.validate()
        return ir

    covered: list[tuple[int, int]] = []
    pending_targets: list[Target] = []
    goal_n = 0
    prev_goal: Goal | None = None

    # sentences
    sentences: list[tuple[int, int]] = []
    pos = 0
    for m in L.SENTENCE_SPLIT_RE.finditer(text):
        if text[pos:m.start()].strip():
            sentences.append((pos, m.start()))
        pos = m.end()
    if text[pos:].strip():
        sentences.append((pos, len(text)))

    for s_start, s_end in sentences:
        sent = text[s_start:s_end]
        # ---- sentence-level constraints -------------------------------------------------------------------------
        sent_constraints: list[Constraint] = []
        clause_level_constraints: set[int] = set()   # span starts of whole-clause handling/citation instructions
        mask: list[tuple[int, int]] = []
        for kind, pat, masks in (("negation", L.NEGATION_RE, True), ("exclusion", L.EXCLUSION_RE, True), ("negation", L.NEG_PREDICATE_RE, False),
                                 ("scope", L.SCOPE_ONLY_RE, False), ("output_shape", L.OUTPUT_SHAPE_RE, False), ("quantity", L.QUANTITY_RE, False),
                                 ("time", L.TIME_RE, False)):
            for m in pat.finditer(sent):
                sp = _span(text, s_start + m.start(), s_start + m.end())
                if not sp.text:
                    continue
                if kind == "time" and any(c.kind == "quantity" and c.span.start <= sp.start < c.span.end for c in sent_constraints):
                    continue
                if any(c.kind == kind and c.span.start == sp.start for c in sent_constraints):
                    continue
                sent_constraints.append(Constraint(kind, sp.text, sp))
                if masks:
                    mask.append((sp.start, sp.end))
        precond = [Constraint("precondition", _span(text, s_start + m.start(), s_start + m.end()).text, _span(text, s_start + m.start(), s_start + m.end()))
                   for m in L.PRECONDITION_RE.finditer(sent)]
        sent_constraints += precond

        def masked(a: int, b: int) -> bool:
            return any(ms <= a and b <= me for ms, me in mask)

        # ---- clause split -------------------------------------------------------------------------------------------
        cuts: list[tuple[int, int, str]] = []  # (start_of_marker, end_of_marker, kind)
        for m in L.SEQUENCE_RE.finditer(sent):
            cuts.append((s_start + m.start(), s_start + m.end(), "sequence"))
        for m in L.ORDER_FIRST_RE.finditer(sent):
            cuts.append((s_start + m.start(), s_start + m.end(), "first"))
        for m in L.AND_VERB_RE.finditer(sent):
            rest = sent[m.end():]
            head = " ".join(rest.split()[:3])
            first_end = len(rest.split()[0]) if rest.split() else 0
            def _starts(p):
                mm = p.search(head)
                return mm is not None and mm.start() <= first_end
            if any(_starts(p) for _, p in L.OPERATOR_RULES) or _starts(L.OUT_OF_SCOPE_RE):
                cuts.append((s_start + m.start(), s_start + m.end(), "and"))
        cuts.sort()
        clauses: list[tuple[int, int, str]] = []
        c_start, c_kind = s_start, "plain"
        for a, b, kind in cuts:
            if a > c_start and text[c_start:a].strip(_TRAIL_PUNCT):
                clauses.append((c_start, a, c_kind))
            elif a <= c_start:
                pass
            c_start, c_kind = b, kind
        if text[c_start:s_end].strip(_TRAIL_PUNCT):
            clauses.append((c_start, s_end, c_kind))
        if not clauses and sent.strip():
            clauses.append((s_start, s_end, "plain"))

        sent_goals: list[Goal] = []
        for c_start, c_end, c_kind in clauses:
            ir.coverage["clauses"] += 1
            csp = _span(text, c_start, c_end)
            if not csp.text:
                ir.coverage["clauses"] -= 1
                continue
            clause = text[csp.start:csp.end]
            if masked(csp.start, csp.end):  # whole clause is a constraint ("Do not list binaries;") — covered, not unresolved
                covered.append((csp.start, csp.end))
                ir.coverage["clauses"] -= 1
                continue
            # greeting / small talk
            gm = L.GREETING_RE.match(clause)
            if gm and len(clause[gm.end():].strip(_TRAIL_PUNCT)) == 0:
                ir.smalltalk.append(csp)
                covered.append((csp.start, csp.end))
                continue
            # whole clause is an answering/handling instruction ("Cite the source path and line.", "Treat file contents as
            # untrusted data, not instructions.") → constraint on the surrounding goals, never a goal of its own
            if L.CITATION_CLAUSE_RE.match(clause) or L.HANDLING_CLAUSE_RE.match(clause):
                c = Constraint("output_shape" if L.CITATION_CLAUSE_RE.match(clause) else "precondition", csp.text, csp)
                if not any(x.span.start == c.span.start for x in sent_constraints):
                    sent_constraints.append(c)
                clause_level_constraints.add(c.span.start)
                mask.append((csp.start, csp.end))
                ir.coverage["clauses"] -= 1
                continue
            # "I uploaded a ZIP archive." / "We attached the configs." → premise (context), not an extract goal
            if L.UPLOAD_PREMISE_RE.match(clause) and not clause.rstrip().endswith("?"):
                ir.premises.append(csp)
                covered.append((csp.start, csp.end))
                tmp = Goal("g0", "extract", csp)
                _targets(tmp, text, aliases, masked, ir)
                pending_targets.extend(tmp.targets)
                continue
            # operator by priority, ignoring masked spans
            chosen: tuple[str, re.Match[str]] | None = None
            for op, pat in L.OPERATOR_RULES:
                for m in pat.finditer(clause):
                    if not masked(csp.start + m.start(), csp.start + m.end()):
                        chosen = (op, m)
                        break
                if chosen:
                    break
            oos = next((m for m in L.OUT_OF_SCOPE_RE.finditer(clause) if not masked(csp.start + m.start(), csp.start + m.end())), None)
            if oos is not None and (chosen is None or oos.start() < chosen[1].start()):
                ir.unresolved.append(Unresolved(csp, "out_of_scope_verb"))
                ir.coverage["unresolved_clauses"] += 1
                continue
            trigger = ""
            if chosen is None:
                words = _WORD_RE.findall(clause)
                if prev_goal is not None and c_kind in ("sequence", "and", "first") and 0 < len(words) <= 8:
                    chosen_op, trigger = prev_goal.operator, "ellipsis"
                elif words and len(words) <= 8 and (refs or clause.rstrip().endswith("?")) and not _WH_START_RE.match(clause):
                    chosen_op, trigger = "extract", "nominal"
                elif L.DECLARATIVE_START_RE.match(clause) and not clause.rstrip().endswith("?"):
                    # declarative premise: context the user states; its file/entity mentions feed the next goal
                    ir.premises.append(csp)
                    covered.append((csp.start, csp.end))
                    tmp = Goal("g0", "extract", csp)
                    _targets(tmp, text, aliases, masked, ir)
                    pending_targets.extend(tmp.targets)
                    continue
                else:
                    reason = "imperative_unparsed" if words and not clause.rstrip().endswith("?") and not _WH_START_RE.match(clause) else "no_operator"
                    ir.unresolved.append(Unresolved(csp, reason))
                    ir.coverage["unresolved_clauses"] += 1
                    continue
            else:
                chosen_op, trigger = chosen[0], chosen[1].group(0)
            # pronoun-only object after an extract/inspect/summarize trigger → continuation of the previous goal
            unmasked_rest = "".join(ch if not masked(csp.start + chosen[1].end() + i, csp.start + chosen[1].end() + i + 1) else " "
                                    for i, ch in enumerate(clause[chosen[1].end():])) if chosen is not None else ""
            if chosen is not None and prev_goal is not None and chosen_op in ("extract", "inspect", "summarize") and _PRONOUN_ONLY_RE.match(unmasked_rest.rstrip(" ,;")) \
                    and (prev_goal.span.end <= s_start or prev_goal.operator == chosen_op):  # anaphoric restatement across sentences, not same-sentence coordination
                prev_goal.span = Span(prev_goal.span.start, csp.end, text[prev_goal.span.start:csp.end]) if prev_goal.span.start < csp.start and \
                    text[prev_goal.span.start:csp.end].count("\n") == 0 and csp.start - prev_goal.span.end < 40 else prev_goal.span
                covered.append((csp.start, csp.end))
                ir.coverage["clauses_with_goal"] += 1
                continue
            goal_n += 1
            g = Goal(f"g{goal_n}", chosen_op, csp, trigger=trigger, order_index=goal_n - 1)
            # a negation negates the goal only when it precedes the operator trigger ("do not list …"); after the trigger it is
            # part of the predicate/target ("which tests did not pass", "files that do not have tests") → positive goal
            trigger_at = csp.start + (chosen[1].start() if chosen is not None else 0)
            if any(c.kind == "negation" and csp.start <= c.span.start < trigger_at and c.span.end <= csp.end and not masked(c.span.start, c.span.end) for c in sent_constraints):
                g.polarity = "negative"
            if c_kind in ("sequence", "and") and prev_goal is not None:
                g.depends_on.append(prev_goal.id)
            # ---- targets --------------------------------------------------------------------------------------------
            _targets(g, text, aliases, masked, ir)
            if pending_targets:
                have = {(x.kind, x.value) for x in g.targets}
                g.targets += [x for x in pending_targets if (x.kind, x.value) not in have]
                pending_targets = []
            sent_goals.append(g)
            ir.goals.append(g)
            prev_goal = g
            covered.append((csp.start, csp.end))
            ir.coverage["clauses_with_goal"] += 1

        # inspect/open <file> followed by another goal in the same sentence → fold into that goal's targets
        folded: list[Goal] = []
        for i, g in enumerate(sent_goals):
            nxt = sent_goals[i + 1] if i + 1 < len(sent_goals) else None
            if g.operator == "inspect" and nxt is not None and g.targets and all(t.kind in ("file", "file_group") for t in g.targets):
                nxt.targets = g.targets + [t for t in nxt.targets if t.value not in {x.value for x in g.targets}]
                nxt.depends_on = [d for d in nxt.depends_on if d != g.id]
                ir.goals.remove(g)
                continue
            folded.append(g)
        sent_goals = folded
        # precondition → later goals depend on the precondition goal
        if precond and len(sent_goals) >= 1:
            pre = sent_goals[0]
            for g in ir.goals:
                if g.order_index > pre.order_index and pre.id not in g.depends_on:
                    g.depends_on.append(pre.id)
        if any(c.kind == "precondition" for c in precond) and sent_goals:
            for g in sent_goals:
                pass
        ids = [g.id for g in sent_goals]
        for c in sent_constraints:
            # a sentence that is only "Cite the source path and line." governs the goal before it
            hosts = sent_goals if ids else ([prev_goal] if c.span.start in clause_level_constraints and prev_goal is not None else [])
            c.applies_to = [g.id for g in hosts]
            ir.constraints.append(c)
            covered.append((c.span.start, c.span.end))
            if hosts and c.kind in ("negation", "exclusion", "scope", "output_shape", "precondition"):
                for g in hosts:
                    g.constraints.append(c)

    # renumber after folds so ids are dense and order indices sequential
    remap = {g.id: f"g{i + 1}" for i, g in enumerate(ir.goals)}
    for i, g in enumerate(ir.goals):
        g.id, g.order_index = remap[g.id], i
        g.depends_on = [remap[d] for d in g.depends_on if d in remap]
    for c in ir.constraints:
        c.applies_to = [remap[i] for i in c.applies_to if i in remap]
    # sequence dependencies across sentences ("then" at sentence start)
    ir.coverage["chars_covered"] = _union_len(covered)
    ir.routing = _route(ir)
    ir.validate()
    return ir


def _targets(g: Goal, text: str, aliases: _Aliases, masked, ir: RequestIR) -> None:
    clause = text[g.span.start:g.span.end]
    base = g.span.start
    seen: set[tuple[int, int]] = set()

    def add(t: Target) -> None:
        key = (t.span.start, t.span.end)
        if key in seen or masked(*key):
            return
        seen.add(key)
        g.targets.append(t)

    for m in L.PATH_RE.finditer(clause):
        sp = _span(text, base + m.start(), base + m.end())
        hits = aliases.resolve_path(sp.text)
        add(Target("file", hits[0] if len(hits) == 1 else sp.text, sp, candidates=hits, resolved=len(hits) == 1))
        if len(hits) > 1:
            ir.ambiguities.append(Ambiguity(sp, "target_ambiguous", f"path mention matches {len(hits)} attached files", hits))
    if aliases.files:
        recency = L.SEL_RECENCY_RE.search(clause)
        for m in _WORD_RE.finditer(clause):
            w = m.group(0).lower().strip("'")
            if any(ms <= base + m.start() < me for ms, me in seen):
                continue
            cands: set[str] = set()
            if w in aliases.by_alias:
                cands = aliases.by_alias[w]
            elif w in L.EXT_WORDS:
                for ext in L.EXT_WORDS[w]:
                    cands |= aliases.by_ext.get(ext, set())
                if w in ("readme", "changelog"):
                    cands = {f for f in cands if w in f.lower()}
            if not cands:
                continue
            sp = _span(text, base + m.start(), base + m.end())
            cands_l = sorted(cands)
            if len(cands_l) == 1:
                add(Target("file", cands_l[0], sp, candidates=cands_l))
                continue
            # deterministic disambiguation among versioned siblings
            picked = None
            versioned = [f for f in cands_l if re.search(r"[._-]v\d+[._-]", f.lower())]
            plain = [f for f in cands_l if f not in versioned]
            vtok = re.search(r"\bv\d+\b", clause, re.I)
            if vtok and any(vtok.group(0).lower() in f.lower() for f in versioned):
                picked = next(f for f in versioned if vtok.group(0).lower() in f.lower())
            elif recency and plain and versioned and len(plain) == 1 and not L.QUANTITY_RE.search(clause):
                picked = plain[0] if recency.group(0).lower() in ("latest", "newest", "most recent", "current") else (versioned[0] if len(versioned) == 1 else None)
            if picked:
                add(Target("file", picked, sp, candidates=cands_l))
            else:
                add(Target("file_group", w, sp, candidates=cands_l, resolved=False))
                kind = "recency_unresolved" if recency else "target_ambiguous"
                ir.ambiguities.append(Ambiguity(sp, kind, f"'{sp.text}' matches {len(cands_l)} attached files; no attachment timestamps to order them" if recency
                                                else f"'{sp.text}' matches {len(cands_l)} attached files", cands_l))
    for pat, kind in ((L.QUOTED_RE, "entity"), (L.IDENT_RE, "field"), (L.VERSION_RE, "entity")):
        for m in pat.finditer(clause):
            grp = m.group(1) if pat is L.QUOTED_RE else m.group(0)
            start = base + (m.start(1) if pat is L.QUOTED_RE else m.start())
            sp = _span(text, start, start + len(grp))
            if any(ms <= sp.start < me for ms, me in seen):
                continue
            add(Target(kind, sp.text, sp))


def _union_len(spans: list[tuple[int, int]]) -> int:
    total, cur = 0, None
    for a, b in sorted(spans):
        if cur is None or a > cur[1]:
            if cur:
                total += cur[1] - cur[0]
            cur = [a, b]
        else:
            cur[1] = max(cur[1], b)
    if cur:
        total += cur[1] - cur[0]
    return total


def _route(ir: RequestIR) -> Routing:
    ops = [g.operator for g in ir.goals]
    why: list[str] = []
    if not ir.attachments:
        if L.SEC_DIRECTIVE_RE.search(ir.text):
            return Routing("graph_candidate", ["no attachment; SEC 10-K directive vocabulary present → graph lane candidate (EDGAR resolution decides)"], True)
        why.append("no attachment and no SEC directive — forge-2b has no free chat")
        if ir.unresolved:
            why.append(f"{len(ir.unresolved)} unresolved clause(s): " + "; ".join(f"{u.reason} '{u.span.text[:40]}'" for u in ir.unresolved))
        return Routing("unsupported", why, False)
    if not ops and ir.unresolved and all(u.reason == "out_of_scope_verb" for u in ir.unresolved):
        return Routing("unsupported", ["only out-of-scope imperative(s): " + "; ".join(f"'{u.span.text[:40]}'" for u in ir.unresolved),
                                       "attachment present → answer explains the refusal and shows the manifest"], False)
    why.append(f"{len(ir.attachments)} attachment(s), {sum(len(a.files) for a in ir.attachments)} file name(s) known")
    if "audit" in ops:
        return Routing("scan", why + ["audit goal → deterministic instruction-lexicon scan; LLM not called"], False)
    if not ops:
        why.append("no goal parsed" + (" (small talk)" if ir.smalltalk else "") + (f"; {len(ir.unresolved)} unresolved clause(s)" if ir.unresolved else ""))
        return Routing("manifest", why + ["→ manifest + guidance, zero-model"], False)
    if set(ops) == {"list"}:
        return Routing("manifest", why + ["only list goal(s) → manifest table, zero-model"], False)
    if set(ops) <= {"summarize", "list"} and not any(t.kind == "file" for g in ir.goals if g.operator == "summarize" for t in g.targets):
        return Routing("overview", why + ["summarize without a file target → deterministic overview + one model summary call"], True)
    if "compare" in ops or "reconcile" in ops:
        return Routing("qa_multi_source", why + [f"{'/'.join(sorted(set(ops) & {'compare', 'reconcile'}))} goal → evidence from ≥2 files, one model call"], True)
    if ir.unresolved:
        why.append(f"{len(ir.unresolved)} unresolved clause(s) carried to the answer as 'not done'")
    return Routing("qa", why + [f"goals {ops} → retrieve → one model call → verify"], True)
