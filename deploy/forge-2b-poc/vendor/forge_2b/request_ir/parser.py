"""DCE-G1/G1R: ``parse_request(utterance, context=None) -> RequestIR`` — deterministic, pure, bounded.

Pipeline: validate input (type / surrogates / size) → digest → protected regions → sentences → clauses (sequence,
coordination, alternative and comma cuts that are followed by an imperative or interrogative head; a sentence that
opens with a condition marker is cut at its first comma) → per clause: else/condition prefix → leading constraints →
clause-level constraint (prohibition / exclusion / requirement, with target_object + breadth) | action trigger → trailing
conditions, target, inline constraints, references | declarative context | unresolved → explicit links (sequence
markers, temporal subordinators, "or") → stats, status, span validation.

Actions named inside a condition ("before running anything", "if I run the script", "until you verify") are recorded
as ``Condition.mentioned_action`` and never become objectives. No I/O, no network, no model, no module-level mutable
state, no evaluation of user text. ``ReadOnlyContext`` referents can only resolve a pronoun — never create an objective.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from . import rules as R
from .schema import (ACTION_CLASS, DEFAULT_LANGUAGE_SCOPE, LANGUAGE_SCOPES, MAX_CLAUSES, MAX_UTTERANCE_CHARS, PARSER_VERSION, SCHEMA_VERSION, Condition, Constraint,
                     ContextStatement, IntentGraph, Link, Mention, Objective, ProtectedRegion, ReadOnlyContext, Reference, RequestIR,
                     Span, Unresolved, utterance_digest)
from .segment import Mask, protected_regions, sentences, trim

# verbs that are at least as often nouns: after a connective they only open a new clause when an object follows
NOUNISH_VERBS = frozenset("output return print total average label tag group set format turn display report note state rate drop post call "
                          "email sum measure patch test audit search diff sort rank estimate bucket review check see read open view name make "
                          "update change fix increase decrease start stop run order process access count list show use build design plan "
                          "release deploy install clear sign record log trigger apply".split())
_OBJECT_START_RE = re.compile(r"\s+(?:the|a|an|all|each|every|any|them|it|this|that|these|those|me|my|our|your|its|their|by|out|up|only|which|"
                              r"what|whether|if|how|where|who|whom|for|from|in|on|to|nothing|anything|everything|no|zero|not a single|нічого|жодних|жодного|\d|[\"“«`'])", re.I)
_DECL_AFTER_NOUNISH_RE = re.compile(r"\s*(?!(?:which|what|whether|if|who|whom|whose|where|when|how|the|a|an|all|every|each|any|this|that|these|those|them|it|"
                                    r"me|my|our|your|its|their|only|just)\b)\S+\s+(?:is|are|was|were|has|have|had|does|do|did)\b", re.I)
_WORD_RE = re.compile(r"[^\W\d_]+", re.U)
_GERUND_RE = re.compile(r"^\s*([A-Za-z]+ing)\b")
_LONE_SURROGATE_RE = re.compile("[\ud800-\udfff]")
_CONTROL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_NOT_TRAILING_BEFORE_RE = re.compile(r"(?:even|as|what|whether|or)\s*$", re.I)
_ONLY_BEFORE_COND_RE = re.compile(r"(?:,\s*|\s+)(?:only|just|тільки|лише)\s*$", re.I)
_ONLY_WORD_RE = re.compile(r"\s*(?:only|just|тільки|лише)\s+", re.I)
_WHETHER_BEFORE_RE = re.compile(r"\bwhether\s*$", re.I)
_NOT_DET_RE = re.compile(r"\s*(?:not|ні|не)\s+(?:the|a|an|this|that|these|those|it|they|he|she|we|you|my|our|your|its|their)\b", re.I)
# after an explicit sequence marker ("then", "потім"), a bare word that is not a function word opens a new clause even when
# the verb is unknown ("then paste the output" → typed no_recognized_action instead of being swallowed by the previous target)
_SEQ_NONCLAUSE_RE = re.compile(r"\s*(?:the|a|an|this|that|these|those|it|its|them|they|he|she|we|you|i|my|our|your|their|his|her|all|any|each|every|some|"
                               r"only|also|again|later|soon|immediately|once|twice|if|that|whether|which|when|how|why|because|since|so|but|or|and|not|as|\d|[\"“«`'(\[]|"
                               r"це|цей|ця|ці|той|та|те|ті|його|її|їх|їхні|мій|моя|мої|наш|наша|наші|ваш|ваша|ваші|всі|усі|кожен|кожна|кожне|лише|тільки|також|знову|пізніше|"
                               r"як|що|щоб|коли|якщо|чи|бо|тому|але|або|і|й|не)\b", re.I)
_BLOCK_KINDS = ("code_fence", "inline_code", "json_like", "quotation", "yaml_like", "command_like", "attachment")
_MUTATING = ("mutate", "execute")
# inside a sentence that is already a list of clauses, ", <unknown verb> <determiner/pronoun> …" opens a clause of its own
# ("Read both logs, line up their timestamps, and identify …") — never a bare noun list (", the services, and the users")
_UNKNOWN_VERB_OBJECT_RE = re.compile(r"\s+(?:the|a|an|all|each|every|any|them|it|this|that|these|those|me|my|our|your|its|their|both|up|out|down|off|"
                                     r"усі|всі|їх|його|її|цей|ці|це|цю|цього|цієї|кожен|кожну|кожне|мого|мою|моє|мої|свого|свою|своє|свої|нашого|нашу|наше|наші|вашого|вашу|ваші|будь-як\w+)\b", re.I)
_PREP_START_RE = re.compile(r"\s*(?:with|for|from|in|on|at|by|to|of|without|via|per|about|after|before|under|over|into|onto|between|among|than|like|"
                            r"з|зі|без|для|від|до|після|перед|у|в|на|про|через|між|як|ніж)\b", re.I)
_INDEFINITE_OBJECT_FIRST_RE = re.compile(r"\s*(?:щось|що-небудь|будь-що|нічого|anything|something|everything)\s+(?=[^\W\d_])", re.I)
_UK_OBJECT_FIRST_NEG_RE = re.compile(r"^\s*(?P<obj>[^\W\d_][^,;:]{0,60}?)\s+не\s+(?P<verb>[^\W\d_]+)\s*[.!…]*\s*$", re.I)
_DEMONSTRATIVE_RE = re.compile(r"\s*(?:this|that|these|those|цей|ця|ці|той|та|ті|цього|цієї|цих|тих)\b", re.I)   # not це/те: usually pronominal
_WH_HEAD_RE = re.compile(r"\s*(?:which|what|who|whom|whose|where|when|why|how|whether|if|який|яка|яке|які|хто|що|де|коли|чому|як|чи|котр\w+)\b", re.I)
_EMPHATIC_DO_RE = re.compile(r"\s*(?:but\s+)?do\s+(?!not\b|n't|so\b|it\b|that\b|this\b|nothing\b|anything\b|any\b|the\b|a\b|an\b|what\b|whatever\b)", re.I)
_REPLY_SHAPE_NOUN_RE = re.compile(r"\b(?:bullets?|bullet points?|lines?|sentences?|words?|paragraphs?|rows?|pages?|слів|речень|рядків|абзац\w*|пункт\w*)\b", re.I)
_PROHIBITED_COORD_RE = re.compile(r"(?:\b(?:must|should|shall|may|can|could|would|will|do|does|did|need)\s*n[o']t|\bnever|\bдо not|\bне(?:\s+(?:можна|треба|слід|варто))?)\s+(?:\w+(?:\s+\w+){0,3})\s*$", re.I)
_DO_PRONOUN_RE = re.compile(r"(?:do|зроби|зробіть|виконай|виконайте) (?P<pro>it|that|this|so|these|those|the same|everything|all of (?:it|that|them)|це|те|так само|так|його|її|їх)\b", re.I)
_WOULD_RE = re.compile(r"^\s*(?:would|might) you\b", re.I)
_POLITE_REQUEST_RE = re.compile(r"\b(?:please|kindly|for me|for us|right away|asap|now|today|mind)\b", re.I)
_WITHOUT_GERUND_RE = re.compile(r"\bwithout\s+(?:first\s+)?[a-z]+ing\b", re.I)
_INDIRECT_OBJECT_RE = re.compile(r"(?:me|us|мені|нам)\s+(?=[^\W\d_]|\d)", re.I)   # indirect-object pronoun before the real object
_WH_COMPLEMENT_RE = re.compile(r"\b(?:how|what|whether|why|which|where|who|whom|that|if|як|що|чи|чому|який|яка|які|де|хто)\b", re.I)
_WH_WORDS = frozenset("what where who whom whose when which why how whether що де хто кого чий коли який яка яке які чому як чи".split())
_NOMINAL_NEG_MARKERS = frozenset(("жодних", "ніяких", "без", "without"))
# English evidence inside an otherwise unrecognised ASCII clause (function words, pronouns, common adverbs); none → uncertain language
_EN_EVIDENCE_RE = re.compile(r"\b(?:the|a|an|and|or|but|is|are|was|were|be|to|of|in|on|at|for|with|by|from|into|onto|about|it|its|this|that|these|those|them|"
                             r"their|they|you|your|we|our|i|me|my|us|he|she|him|her|who|what|which|how|when|where|why|not|no|don'?t|do|does|did|can|could|"
                             r"should|would|will|may|must|instead|up|down|out|over|again|also|then|than|here|there|now|only|just|all|any|some|each|every|"
                             r"please|if|unless|until|after|before|once|while|so|as|like|same|new|old|first|last|next|more|most|less|very|too|both|either|"
                             r"neither|own|other|another|such|per|via|without|within|between|through|against|across|toward|towards|under|above|below)\b", re.I)
_SUBJECT_FRONTED_RULES = frozenset(("en.prohibition.subject_active", "en.prohibition.subject_passive", "en.prohibition.off_limits"))
_CONTRAST_NOT_RE = re.compile(r"(?:,|;)?\s+(?:though|although|but|yet|however)\s+(?:not|never)\b", re.I)   # G1R3C: ", though not to production"
_TEMPORAL_TAIL_RE = re.compile(r"\s+(?:today|tonight|tomorrow|now|yet|for now|this (?:week|sprint|time)|at (?:this|the) (?:point|time|moment)|until further notice|"
                               r"сьогодні|зараз|поки що|наразі|цього тижня|до подальшого)\s*$", re.I)
_HEAD_BEFORE_PREP_RE = re.compile(r"^(.+?)\s+(?:to|in|on|of|for|at|into|onto|against|towards|with|within|across|у|в|до|на|для|з|зі|по|щодо)\s+", re.I)
_REPLY_ARTEFACT_NOT_RE = re.compile(r"\s+(?:handler|parser|object|class|header|headers|code|module|file|schema|type|body|payload|queue|topic|bus|table|log)\b", re.I)


@dataclass
class _Clause:
    start: int
    end: int
    sent: int
    joiner: str                     # "" | "sequence" | "coord" | "comma" | "alt" | "cond"
    marker: Optional[tuple[int, int]] = None   # span of the explicit sequence / "or" word


class _State:
    def __init__(self, text: str, mask: Mask, context: Optional[ReadOnlyContext]):
        self.text, self.mask, self.context = text, mask, context
        self.g = IntentGraph()
        self.n = {"o": 0, "c": 0, "l": 0, "u": 0, "k": 0, "q": 0}
        self.pending_after: Optional[tuple[str, tuple[int, int]]] = None    # (objective id, subordinator span): next objective depends on it
        self.pending_before: Optional[tuple[str, tuple[int, int]]] = None   # this objective depends on the next one
        self.last_obj_sent: dict[int, str] = {}                              # sentence index → last objective id in it
        self.pending_cst: dict[int, list[Constraint]] = {}                   # sentence index → clause constraints awaiting an objective
        self.sent_conditions: dict[int, list[Condition]] = {}                # sentence index → sentence-level conditions (govern later nodes)
        self.last_cond_id: Optional[str] = None                              # most recent if/unless/until condition (target of "otherwise")
        self.pending_joiner: dict[int, tuple[str, tuple[int, int]]] = {}    # sentence index → (sequence|alt, marker span) carried over a condition clause
        self.cst_sent: dict[str, int] = {}                                   # constraint id → sentence index (same-sentence antecedents)
        self.last_mention: Optional[tuple[str, Optional[Mention]]] = None    # most recent operation named anywhere ("Do not do so" refers to it)
        self.immediate_clause = False     # "…, meanwhile describe the plan" — the clause is exempt from the sentence-initial condition
        self.language_scope = DEFAULT_LANGUAGE_SCOPE
        self.diacritic_clauses: list[tuple[int, int]] = []                  # Latin clauses with non-ASCII letters (uncertain language)
        self.sent_spans: list[tuple[int, int]] = []
        self.sent_script: dict[int, str] = {}                                # sentence index → latin | diacritic | non_latin (en scope)
        self.unsupported_sents: set[int] = set()
        self.covered: list[tuple[int, int]] = []
        self.block_ids = [f"p{i}" for i, r in enumerate(mask.regions, 1) if r.kind in _BLOCK_KINDS]

    def nid(self, prefix: str) -> str:
        self.n[prefix] += 1
        return f"{prefix}{self.n[prefix]}"

    def mention(self, a: int, b: int, *, lead_punct: bool = False) -> Optional[Mention]:
        a, b = trim(self.text, a, b, strip_leading_punct=lead_punct)
        return Mention(self.text[a:b], Span(a, b)) if b > a else None

    def antecedent(self, sent: int) -> Optional[Any]:
        """Most recent objective with a concrete target; failing that, the target_object of a narrow prohibition / exclusion
        **in the same sentence** ("Do not delete logs, but summarize them" → *them* = logs, resolved to c1). A prohibition in
        an earlier sentence never lends its object ("Do not modify the lockfile; … only report it" keeps *it* unresolved)."""
        objs = [o for o in self.g.objectives if o.target is not None]
        if objs:
            return max(objs, key=lambda n: n.source_span.start)
        csts = [c for c in self.g.constraints if c.kind in ("prohibition", "exclusion") and c.target_object is not None
                and c.breadth == "narrow" and self.cst_sent.get(c.id) == sent]
        if csts:
            return max(csts, key=lambda n: n.source_span.start)
        # "After sign-off on the migration bundle, apply it to prod-db-02." — a sentence-initial approval condition naming exactly
        # one material / operation noun lends that noun (DCE-G1R3C); several candidates keep the pronoun unresolved
        appr = [q for q in self.sent_conditions.get(sent, []) if q.rule.endswith(".approval_np")]
        if len(appr) == 1:
            nouns = list(R.ANTECEDENT_NOUN_RE.finditer(appr[0].text))
            if len(nouns) == 1:
                return appr[0]
        # "The migration bundle must not change. Summarize what it contains." — a subject-fronted prohibition is syntactically a
        # statement about its subject; when it is the only such statement the subject is the antecedent (DCE-G1R3C, sheet v4 rule 15)
        fronted = [c for c in self.g.constraints if c.kind == "prohibition" and c.target_object is not None
                   and c.rule in _SUBJECT_FRONTED_RULES and self.cst_sent.get(c.id, sent) < sent]
        if len(fronted) == 1 and not self.g.context_statements and not self.block_ids:
            return fronted[0]
        # "Here is the migration dry-run output. … execute it" — a single earlier context statement naming exactly one material /
        # operation noun is the antecedent (DCE-G1R3B rule 11); zero or several candidates keep the pronoun unresolved
        if self.block_ids:                                    # a quoted / fenced block outranks a statement as the referent of "it"
            return None
        cands = []
        for k in self.g.context_statements:
            groups, last_end = 0, None
            ktext = "".join(" " if self.mask.covers(k.source_span.start + j) else ch for j, ch in enumerate(k.text))   # protected text is opaque
            for m in R.ANTECEDENT_NOUN_RE.finditer(ktext):        # "the migration dry-run output" is one phrase, "the log and the script" are two
                gap = ktext[last_end:m.start()] if last_end is not None else None
                if gap is None or len(gap) > 14 or re.search(r"[,;]|\b(?:and|or|та|і|й|або)\b", gap):
                    groups += 1
                last_end = m.end()
            if groups:
                cands.append((k, groups))
        if len(cands) == 1 and cands[0][1] == 1:
            return cands[0][0]
        return None

    def for_each(self, sent: int) -> Optional[str]:
        """The for_each condition governing this sentence, if any ("For every service, state its image tag" → *its* = q1)."""
        for q in self.sent_conditions.get(sent, []):
            if q.kind == "for_each":
                return q.id
        return None

    def govern(self, sent: int, node_id: str) -> None:
        """Attach a freshly emitted node to every sentence-level condition of its sentence — except a condition whose
        complement branch has already opened ("if …, say so; otherwise confirm" → *confirm* belongs to the else only)."""
        if self.immediate_clause:
            return
        conds = self.sent_conditions.get(sent, [])
        negated = {q.negates for q in conds if q.kind == "else" and q.negates}
        for q in conds:
            if q.id not in negated:
                q.applies_to_ids.append(node_id)


# --- public API ----------------------------------------------------------------------------------------------------

def parse_request(utterance: str, context: Optional[ReadOnlyContext] = None, *, strict: bool = False,
                  language_scope: str = DEFAULT_LANGUAGE_SCOPE) -> RequestIR:
    """Parse one utterance. ``strict=True`` additionally runs full JSON-Schema validation on the result (tests do this
    for every corpus case); the span/digest integrity check always runs.

    ``language_scope`` (DCE-G1R3C): ``"en"`` (default) interprets **English** user-authored instructions only. A clause whose
    instruction text — outside protected regions (code, quotes, URLs, paths, attachments) — contains letters of a non-Latin
    script is recorded as ``unresolved(kind="unsupported_language")`` and yields no objective, constraint or condition; a
    Latin-script clause with diacritics that produces no recognised English action is recorded the same way (uncertain,
    never assumed English). ``"legacy-multilingual"`` is an explicit opt-in that keeps the pre-0.5 behaviour for historical
    regression material (deferred scope); it is never the default and no consumer uses it. The result is descriptive only.
    """
    if not isinstance(utterance, str):
        raise TypeError("utterance must be str")
    if context is not None and not isinstance(context, ReadOnlyContext):
        raise TypeError("context must be ReadOnlyContext or None")
    if language_scope not in LANGUAGE_SCOPES:
        raise ValueError(f"language_scope must be one of {LANGUAGE_SCOPES}")
    digest = utterance_digest(utterance)
    base = dict(schema_version=SCHEMA_VERSION, parser_version=PARSER_VERSION, digest=digest, utterance_chars=len(utterance),
                limits={"max_utterance_chars": MAX_UTTERANCE_CHARS, "max_clauses": MAX_CLAUSES},
                context_digest=context.digest() if context else None, language_scope=language_scope)
    if _LONE_SURROGATE_RE.search(utterance) or _CONTROL_RE.search(utterance):
        return _finish(RequestIR(status="rejected_invalid_text", language_hint="und", graph=IntentGraph(), stats=_stats(IntentGraph(), 0, 0), **base), utterance, strict)
    if len(utterance) > MAX_UTTERANCE_CHARS:
        return _finish(RequestIR(status="rejected_too_large", language_hint=_language_hint(utterance[:512]), graph=IntentGraph(),
                                 stats=_stats(IntentGraph(), 0, len(utterance.strip())), **base), utterance, strict)
    if not utterance.strip():
        return _finish(RequestIR(status="empty", language_hint="und", graph=IntentGraph(), stats=_stats(IntentGraph(), 0, 0), **base), utterance, strict)

    regions = protected_regions(utterance)
    mask = Mask(regions)
    st = _State(utterance, mask, context)
    st.language_scope = language_scope
    for i, r in enumerate(regions, 1):
        st.g.protected_regions.append(ProtectedRegion(f"p{i}", r.kind, Span(r.start, r.end)))

    clauses: list[_Clause] = []
    sents = sentences(utterance, mask)
    st.sent_spans = list(sents)
    if language_scope == "en":
        st.sent_script = {si: _instruction_script(st, a, b) for si, (a, b) in enumerate(sents)}
    for si, (a, b) in enumerate(sents):
        clauses.extend(_split_clauses(utterance, a, b, si, mask))
    truncated_from: Optional[int] = None
    if len(clauses) > MAX_CLAUSES:
        truncated_from = clauses[MAX_CLAUSES].start
        clauses = clauses[:MAX_CLAUSES]
    for c in clauses:
        _process_clause(st, c)
    # "Suppose we deployed X tonight — explain what would happen." — a condition-only sentence followed by a dash/colon governs the
    # nodes of the sentence it introduces (the dash is a sentence terminator for segmentation, not for scope)
    for si in range(len(sents) - 1):
        qs = [q for q in st.sent_conditions.get(si, []) if not q.applies_to_ids]
        gap = utterance[sents[si][1]:sents[si + 1][0]]
        if not qs or not gap.strip() or gap.strip(" \t\r\n—–-:") or st.sent_conditions.get(si + 1):
            continue
        a1, b1 = sents[si + 1]
        for node in [*st.g.objectives, *st.g.unresolved]:
            if a1 <= node.source_span.start < b1:
                for q in qs:
                    q.applies_to_ids.append(node.id)
    if not clauses:                       # only terminators / punctuation: typed noise, never a silent empty "ok"
        a, b = len(utterance) - len(utterance.lstrip()), len(utterance.rstrip())
        _unresolved(st, 0, a, b, "no_recognized_action", "noise.punctuation_only")
        clauses = [_Clause(a, b, 0, "")]
    if truncated_from is not None:
        a, b = trim(utterance, truncated_from, len(utterance))
        st.g.unresolved.append(Unresolved(st.nid("u"), "truncated", utterance[a:b], Span(a, b), "limit.max_clauses"))
        st.covered.append((a, b))
    for i, u in enumerate(st.g.unresolved):       # a diacritic Latin clause with no recognised English action: uncertain language, not "English"
        if u.kind != "no_recognized_action":
            continue
        uncertain = any(a <= u.source_span.start < b for a, b in st.diacritic_clauses)
        if not uncertain and st.language_scope == "en" and not st.mask.overlaps(u.source_span.start, u.source_span.end):
            # an ASCII-Latin clause of several words with *no* English function word and no recognised action ("Supprime les
            # anciennes sauvegardes") is not evidence of English either → abstain as uncertain language rather than "English, unknown verb"
            words = re.findall(r"[^\W\d_]+", u.text)
            uncertain = len(words) >= 3 and not _EN_EVIDENCE_RE.search(u.text) and not R.ANTECEDENT_NOUN_RE.search(u.text)
        if uncertain:
            st.g.unresolved[i] = Unresolved(u.id, "unsupported_language", u.text, u.source_span, "scope.language.uncertain", referent=u.referent,
                                            objective_id=u.objective_id)

    stats = _stats(st.g, len(clauses) + (1 if truncated_from is not None else 0), len(utterance.strip()), st.covered)
    status = "partial" if truncated_from is not None else ("ok_with_unresolved" if st.g.unresolved else "ok")
    return _finish(RequestIR(status=status, language_hint=_language_hint(utterance), graph=st.g, stats=stats, **base), utterance, strict)


def _finish(ir: RequestIR, utterance: str, strict: bool) -> RequestIR:
    ir.check_spans(utterance)
    if strict:
        ir.validate()
    return ir


# --- segmentation into clauses -----------------------------------------------------------------------------------

def _opens_clause(text: str, pos: int, end: int, *, imperative_only: bool = False) -> bool:
    rest = text[pos:end]
    if not (R.IMPERATIVE_LOOKAHEAD_RE.match(rest) or (not imperative_only and R.INTERROGATIVE_LOOKAHEAD_RE.match(rest))):
        return False
    w = _WORD_RE.search(rest)
    if w and w.start() <= 1 and w.group(0).lower() in NOUNISH_VERBS and not _OBJECT_START_RE.match(rest, w.end()):
        return False
    return True


def _sequence_opens_unknown(text: str, pos: int, end: int, mask: Mask) -> bool:
    """After a sequence marker: a clause with an unknown verb still opens ("then paste the output"); a noun phrase does not
    ("list the ports, then the users")."""
    rest = text[pos:end]
    w = _WORD_RE.search(rest)
    if not w or w.start() > 1 or mask.covers(pos + w.start()) or _SEQ_NONCLAUSE_RE.match(rest):
        return False
    return bool(_OBJECT_START_RE.match(rest, w.end()) or R.NULL_OBJECT_CLAUSE_RE.match(rest) or re.match(r"\s+[^\W\d_]", rest[w.end():]))


def _coord_opens_unknown(text: str, pos: int, end: int, mask: Mask, sentence: str) -> bool:
    """After and/та/і inside an imperative sentence: "<unknown verb> <determiner/pronoun> …" is a clause of its own
    ("Напиши план і дочекайся мого дозволу" → the wait is typed, not swallowed into the first object)."""
    if not R.IMPERATIVE_LOOKAHEAD_RE.match(sentence) or _WH_COMPLEMENT_RE.search(text[end - len(sentence):pos]):
        return False
    rest = text[pos:end]
    w = _WORD_RE.search(rest)
    if (not w or w.start() > 0 or mask.covers(pos) or _SEQ_NONCLAUSE_RE.match(rest) or _PREP_START_RE.match(rest)
            or w.group(0).lower() in NOUNISH_VERBS or w.group(0).lower() in _WH_WORDS or R.INTERROGATIVE_LOOKAHEAD_RE.match(rest)):
        return False
    return bool(_UNKNOWN_VERB_OBJECT_RE.match(rest, w.end()))


def _condition_kind(marker: str) -> Optional[str]:
    if marker.strip().lower() == "should":          # inverted conditional "Should X exceed Y, …" (lookahead-guarded in CONDITION_MARKERS)
        return "if"
    for kind, pat in R.CONDITION_MARKERS:
        for probe in (marker, marker + " x", marker + ","):   # markers may carry a lookahead on what follows ("for each <noun>", "for those,")
            m = re.match(pat, probe, re.I)
            if m and m.end() == len(marker):
                return kind
    return None


def _condition_opens(text: str, pos: int, end: int, mask: Mask) -> Optional[tuple[int, int]]:
    """If a condition clause opens at ``pos`` ("if …,", "for each CSV,", "before running anything,"), return the span of the
    first comma after it (where the governed clause starts); None otherwise. Temporal markers need a real clause."""
    rest = text[pos:end]                                   # (``^`` does not anchor at ``pos`` with re.match(text, pos))
    m = R.CONDITION_START_RE.match(rest)
    if not m or mask.overlaps(pos, pos + m.end()):
        return None
    kind = _condition_kind(m.group(0).strip(" ,\t\n").lower())
    if kind in ("after", "before") and not R.CLAUSE_AFTER_MARKER_RE.match(rest[m.end():]):
        return None
    mc = R.COMMA_RE.search(rest, len(m.group(0).rstrip(" ,\t\n")))    # "for those, extract …" — the marker may end at the comma
    while mc and mask.overlaps(pos + mc.start(), pos + mc.end()):
        mc = R.COMMA_RE.search(rest, mc.end())
    return (pos + mc.start(), pos + mc.end()) if mc else None


def _split_clauses(text: str, s_start: int, s_end: int, sent: int, mask: Mask) -> list[_Clause]:
    sentence = text[s_start:s_end]
    cuts: list[tuple[int, int, str, Optional[tuple[int, int]]]] = []
    cond_cuts: list[tuple[int, int]] = []

    def opens(b: int, *, imperative_only: bool) -> bool:
        if _opens_clause(text, b, s_end, imperative_only=imperative_only):
            return True
        mm = R.MEANWHILE_RE.match(text, b, s_end)           # ", а поки опиши план" / ", in the meantime summarize …"
        if mm and _opens_clause(text, mm.end(), s_end, imperative_only=imperative_only):
            return True
        cc = _condition_opens(text, b, s_end, mask)        # ", then if they pass, deploy …" — a condition opens the clause
        if cc:
            cond_cuts.append(cc)
            return True
        return False

    # an interrogative head opens a joined clause only inside a question ("Which jobs timed out, and what was the longest run?");
    # in an imperative sentence "explain when it fires and what it removes" the wh-phrase is part of the object
    question = sentence.rstrip().endswith("?") or bool(R.INTERROGATIVE_LOOKAHEAD_RE.match(sentence))
    for m in R.SEQUENCE_RE.finditer(sentence):
        a, b = s_start + m.start(), s_start + m.end()
        if mask.overlaps(a, b) or not (opens(b, imperative_only=not question) or _sequence_opens_unknown(text, b, s_end, mask) or
                                       (not mask.covers(b) and R.SEQ_NOMINAL_RE.match(text, b, s_end))):   # ", then a detailed remediation plan"
            continue
        wa, wb = trim(text, a, b, strip_leading_punct=True)
        cuts.append((a, b, "sequence", (wa, wb)))
    for m in R.COORD_RE.finditer(sentence):
        a, b = s_start + m.start(), s_start + m.end()
        if mask.overlaps(a, b) or not (opens(b, imperative_only=not question) or R.FIRST_PERSON_CLAUSE_RE.match(text, b) or
                                       _coord_opens_unknown(text, b, s_end, mask, sentence) or
                                       _CONTRAST_NOT_RE.match(text, a, s_end)):   # ", though not to production" — a contrast exclusion (G1R3C)
            continue                                   # "…, and I will run it myself" — the operator's own statement opens a clause too
        cuts.append((a, b, "coord", None))
    for m in R.ALTERNATIVE_RE.finditer(sentence):
        a, b = s_start + m.start(), s_start + m.end()
        if mask.overlaps(a, b) or not opens(b, imperative_only=True):
            continue
        seg_start = max([s_start] + [cb for _, cb, *_ in cuts if cb <= a] + [cb for _, cb in cond_cuts if cb <= a])
        if _PROHIBITED_COORD_RE.search(text, seg_start, a):           # "you must not detach or edit a policy" — "or edit" continues the prohibition
            continue
        if _WHETHER_BEFORE_RE.search(text, s_start, a) or _NOT_DET_RE.match(text, b, s_end):   # "whether or not the service …"
            continue
        wa, wb = trim(text, a, b, strip_leading_punct=True)
        cuts.append((a, b, "alt", (wa, wb)))
    for m in R.COMMA_RE.finditer(sentence):
        a, b = s_start + m.start(), s_start + m.end()
        if mask.overlaps(a, b) or not (_opens_clause(text, b, s_end, imperative_only=not question) or R.FIRST_PERSON_CLAUSE_RE.match(text, b)):
            continue
        cuts.append((a, b, "comma", None))
    if any(k in ("coord", "sequence", "alt") for _, _, k, _ in cuts) or (len(cuts) >= 1 and R.IMPERATIVE_LOOKAHEAD_RE.match(sentence)):
        # the sentence is a list of clauses: a comma segment that starts with an unknown verb + determiner/pronoun is a clause too
        # ("Read both logs, line up their timestamps, and identify …" → the middle step is typed, not swallowed by the first object)
        for m in R.COMMA_RE.finditer(sentence):
            a, b = s_start + m.start(), s_start + m.end()
            if mask.overlaps(a, b) or any(c[0] == a for c in cuts):
                continue
            rest = text[b:s_end]
            w = _WORD_RE.search(rest)
            if (w and w.start() == 0 and not mask.covers(b) and not _SEQ_NONCLAUSE_RE.match(rest) and not _PREP_START_RE.match(rest)
                    and not R.CONDITION_START_RE.match(rest) and not R.ELSE_START_RE.match(rest) and not R.TRAILING_CONDITION_RE.match(" " + rest)
                    and w.group(0).lower() not in NOUNISH_VERBS and _UNKNOWN_VERB_OBJECT_RE.match(rest, w.end())):
                cuts.append((a, b, "comma", None))
    # a sentence (or a joined clause) that opens with a condition ("If …,", "For each CSV,", "Before running anything,")
    # is cut at the condition's first comma whatever follows — the condition clause is then processed on its own
    cc0 = _condition_opens(text, s_start, s_end, mask)
    if cc0:
        cond_cuts.append(cc0)
    if R.NO_NOUN_HEAD_RE.match(sentence) and not any(k == "comma" for _, _, k, _ in cuts):
        mcm = R.COMMA_RE.search(sentence)
        if mcm and not mask.overlaps(s_start + mcm.start(), s_start + mcm.end()) and not R.NO_NOUN_RE.match(sentence):
            cuts.append((s_start + mcm.start(), s_start + mcm.end(), "comma", None))
    for ca, cb in cond_cuts:                       # a condition cut supersedes a plain comma cut at the same offset
        cuts = [c for c in cuts if not (c[2] == "comma" and c[0] == ca)]
        cuts.append((ca, cb, "cond", None))
    cuts.sort(key=lambda c: (c[0], -c[1]))
    out: list[_Clause] = []
    c_start, joiner, marker = s_start, "", None
    m0 = R.SEQUENCE_START_RE.match(sentence)          # "Then compare …" at sentence start
    if m0 and (_opens_clause(text, s_start + m0.end(), s_end) or _sequence_opens_unknown(text, s_start + m0.end(), s_end, mask)):
        wa, wb = trim(text, s_start, s_start + m0.end(), strip_leading_punct=True)
        c_start, joiner, marker = s_start + m0.end(), "sequence", (wa, wb)
    last_end = c_start
    for a, b, kind, mk in cuts:
        if a < last_end:
            continue
        if text[c_start:a].strip(" \t\r\n,;:"):
            out.append(_Clause(c_start, a, sent, joiner, marker))
        c_start, joiner, marker, last_end = b, kind, mk, b
    if text[c_start:s_end].strip(" \t\r\n,;:"):
        out.append(_Clause(c_start, s_end, sent, joiner, marker))
    # a clause that is only "First," / "Then," (stranded by a comma cut) is a prefix of the clause that follows
    merged: list[_Clause] = []
    for idx, cl in enumerate(out):
        body = text[cl.start:cl.end].strip(" \t\r\n,;:")
        nxt = out[idx + 1] if idx + 1 < len(out) else None
        # likewise "Do not," / "Never, for any reason," stranded ahead of the verb — the prohibition marker belongs to the next clause
        if nxt is not None and body and (R.FIRST_RE.fullmatch(body + " ") or R.SEQUENCE_START_RE.fullmatch(body + " ") or
                                         R.PROHIBITION_START_RE.fullmatch(body + " ") or R.INSTEAD_RE.fullmatch(body + " ") or
                                         R.ELSE_START_RE.fullmatch(body + " ")):          # "otherwise, describe the failure"
            if R.SEQUENCE_START_RE.fullmatch(body + " "):
                wa, wb = trim(text, cl.start, cl.end, strip_leading_punct=True)
                out[idx + 1] = _Clause(cl.start, nxt.end, nxt.sent, "sequence", (wa, wb))
            else:
                out[idx + 1] = _Clause(cl.start, nxt.end, nxt.sent, cl.joiner, cl.marker)
            continue
        merged.append(cl)
    return merged


# --- clause analysis ----------------------------------------------------------------------------------------------

def _strip_prefixes(seg: str) -> int:
    """Return the offset where clause content starts (bullets, labels, politeness and 'first' prefixes removed)."""
    i, changed = 0, True
    while changed:
        changed = False
        for pat in (R.BULLET_RE, R.LABEL_RE, R.FIRST_RE, R.INSTEAD_RE, *R.PREFIX_RES):
            m = pat.match(seg[i:])
            if m and m.end() > 0:
                if pat is R.LABEL_RE and not (R.IMPERATIVE_LOOKAHEAD_RE.match(seg[i + m.end():]) or R.INTERROGATIVE_LOOKAHEAD_RE.match(seg[i + m.end():])):
                    continue   # "list its keys: {…}" is not a label; "Ports: list them" is
                i += m.end()
                changed = True
    return i


def _match_action(rest: str, *, interrogative: bool = True, gerund: bool = False) -> Optional[tuple[str, str, int]]:
    """→ (action, family, trigger_end) for the first rule that matches at the start of ``rest``."""
    for action, fam, pat in R.ACTION_RULES:
        if fam == "interrogative" and not interrogative:
            continue
        m = pat.match(rest)
        if m:
            return action, fam, m.end()
    if gerund:
        g = _GERUND_RE.match(rest)
        if g:
            stem = g.group(1)[:-3]
            for base in (stem, stem + "e", stem[:-1] if len(stem) > 2 and stem[-1] == stem[-2] else stem):
                for action, fam, pat in R.ACTION_RULES:
                    if fam == "imperative" and pat.fullmatch(base):
                        return action, "gerund", g.end()
    return None


def _mentioned_action(rest: str) -> Optional[tuple[str, int]]:
    """The verb a condition or prohibition merely *mentions* (imperative, finite, gerund or participle form) → (action, end)."""
    m = R.COND_SUBJECT_RE.match(rest)
    off = m.end() if m else 0
    mi = _INDEFINITE_OBJECT_FIRST_RE.match(rest, off)      # "перш ніж щось виконувати" / "before anything is executed" — object fronted
    if mi:
        off = mi.end()
    hit = _match_action(rest[off:], interrogative=False, gerund=True)
    if hit:
        return hit[0], off + hit[2]
    for action, pat in R.MENTION_FORMS:
        mm = pat.match(rest[off:].lstrip())
        if mm:
            return action, off + (len(rest[off:]) - len(rest[off:].lstrip())) + mm.end()
    return None


def _coordinated_prohibition(st: "_State", text: str, after_verb: int, v_end: int, ment: Optional[tuple[str, int]], obj: Any,
                             coord_actions: list[str]) -> tuple[Optional[tuple[str, int]], Any]:
    """DCE-G1R3C: "do not save or run it" / "never push or merge to main" — coordinated prohibited verbs share one object.
    Returns the (possibly recovered) first action and the shared object; extra actions are appended to *coord_actions*."""
    mc = R.COORD_VERB_RE.match(text[after_verb:v_end])
    if not mc:
        return ment, obj
    v2 = after_verb + mc.end()
    ment2 = _mentioned_action(text[v2:v_end])
    if not ment2:
        return ment, obj
    shared = st.mention(v2 + ment2[1], v_end)
    if ment is None:                                   # "push" alone is not a verb we type; "push to main" is → recover it with the shared object
        w0 = after_verb
        while w0 > 0 and not text[w0 - 1].isspace():
            w0 -= 1
        first = text[w0:after_verb]
        rec = _mentioned_action(f"{first} {text[v2 + ment2[1]:v_end].strip()}")
        if not rec:
            return ment, obj
        ment = (rec[0], after_verb - w0)
    if ment2[0] != ment[0]:
        coord_actions.append(ment2[0])
    return ment, shared


def _participle_action(part: str) -> Optional[str]:
    """'deleted' → remove, 'executed' → run, … via the imperative rules (strip -ed / -d / UK participle endings)."""
    p = part.lower()
    if p in R.PASSIVE_PARTICIPLES:
        return R.PASSIVE_PARTICIPLES[p]
    stems = [p, p[:-1], p[:-2]] + ([p[:-3] + "y"] if p.endswith("ied") else [])
    for stem in stems:
        hit = _match_action(stem, interrogative=False)
        if hit and hit[2] == len(stem):
            return hit[0]
    return None


def _trailing_conditions(st: _State, a: int, b: int) -> tuple[int, list[tuple[str, int, int, Optional[str]]]]:
    """Split explicit trailing qualifiers out of [a, b): → (new end, [(kind, start, end, mentioned_action), …])."""
    text = st.text
    found: list[tuple[str, int]] = []
    for m in R.TRAILING_CONDITION_RE.finditer(text, max(0, a - 1), b):
        ms = m.start()
        word_start = ms + len(m.group(0)) - len(m.group(0).lstrip(", \t\n"))
        if st.mask.covers(word_start) or word_start <= a or _NOT_TRAILING_BEFORE_RE.search(text[max(a, ms - 8):ms + 1]):
            continue
        kind = _condition_kind(text[word_start:m.end()].lower())
        if kind is None or (kind in ("after", "before") and not R.CLAUSE_AFTER_MARKER_RE.match(text[m.end():b])):
            continue
        found.append((kind, ms))
    if not found:
        return b, []
    # "only after I approve" / "тільки після того, як …": the intensifier belongs to the condition, not to the object
    found = [(kind, (_ONLY_BEFORE_COND_RE.search(text, a, ms).start() if _ONLY_BEFORE_COND_RE.search(text, a, ms) else ms)) for kind, ms in found]
    out = []
    for idx, (kind, ms) in enumerate(found):
        ce = found[idx + 1][1] if idx + 1 < len(found) else b
        ca, cb = trim(text, ms, ce, strip_leading_punct=True)
        if cb <= ca:
            continue
        only = _ONLY_WORD_RE.match(text[ca:cb])
        mk = R.CONDITION_START_RE.match(text[ca + (only.end() if only else 0):cb])
        ment = _mentioned_action(text[ca + (only.end() if only else 0) + mk.end():cb]) if mk else None
        out.append((kind, ca, cb, ment[0] if ment else None))
    return found[0][1], out


def _emit_condition(st: _State, c: _Clause, kind: str, a: int, b: int, rule: str, *, mentioned: Optional[str] = None,
                    applies: Optional[list[str]] = None, negates: Optional[str] = None, sentence_level: bool = False) -> Condition:
    a, b = trim(st.text, a, b, strip_leading_punct=True)
    q = Condition(st.nid("q"), kind, st.text[a:b], Span(a, b), rule, applies_to_ids=list(applies or []), mentioned_action=mentioned, negates=negates)
    st.g.conditions.append(q)
    st.covered.append((a, b))
    if mentioned:
        st.last_mention = (mentioned, None)
    if sentence_level:
        st.sent_conditions.setdefault(c.sent, []).append(q)
    if kind in ("if", "unless", "until"):
        st.last_cond_id = q.id
    return q


def _breadth(obj: Optional[Mention]) -> str:
    return "global" if obj is None or R.GENERIC_OBJECT_RE.match(obj.text) else "narrow"


_CLASS_NOUN_RE = re.compile(r"^\s*(?!(?:the|this|that|these|those|my|our|your|its|their|his|her|цей|ця|це|ці|той|та|те|ті|мій|моя|наш|наша|ваш|ваша)\b)"
                            r"(?:[a-z][a-z-]*\s+){0,2}[a-z][a-z-]*(?:s|es|ies|ands|commands)\b(?:\s+(?:today|tonight|yet|now|for now|during this review|this week|сьогодні|зараз|поки що))?\s*$|"
                            r"^\s*(?:жодних\s+)?[а-яіїєґ'’-]+(?:ів|ей|ань|ок|ень|ів|ин)\s*$", re.I)


def _class_breadth(obj: Optional[Mention]) -> str:
    """Breadth of a nominal / negative-object prohibition: a bare plural class noun ("scripts", "shell commands", "скриптів") is
    the whole class → global; a determined or named object ("the database pods", "deploy.yaml") stays narrow."""
    if obj is None or R.GENERIC_OBJECT_RE.match(obj.text):
        return "global"
    head = _HEAD_BEFORE_PREP_RE.match(obj.text)          # "commands against the production host" → the class "commands"
    probe = head.group(1) if head else obj.text
    return "global" if _CLASS_NOUN_RE.match(probe) else "narrow"


def _process_clause(st: _State, c: _Clause) -> None:
    text = st.text
    cs, ce = trim(text, c.start, c.end, strip_leading_punct=True)
    if cs >= ce:
        ra, rb = c.start, c.end
        while ra < rb and text[ra].isspace():
            ra += 1
        while rb > ra and text[rb - 1].isspace():
            rb -= 1
        if rb > ra:
            _unresolved(st, c.sent, ra, rb, "no_recognized_action", "noise.punctuation_only")
        return
    if st.mask.inside(cs, ce):       # a clause that is entirely a code block / quotation is data, not an instruction
        st.covered.append((cs, ce))
        return
    if R.STRANDED_JOINER_RE.match(text[cs:ce]):   # "; however, do not …" splits into a bare "however" — a joiner, not a request (G1R3C)
        st.covered.append((cs, ce))
        return
    seg = text[cs:ce]
    if st.language_scope == "en":
        script = st.sent_script.get(c.sent, "latin")
        if script == "non_latin":                  # Ukrainian / Russian / mixed / any non-Latin instruction text in the sentence: out of scope, never guessed
            if c.sent not in st.unsupported_sents:  # one node per sentence, spanning the whole sentence (every clause of it is withheld)
                st.unsupported_sents.add(c.sent)
                sa, sb = trim(text, *st.sent_spans[c.sent])
                _unresolved(st, c.sent, sa, sb, "unsupported_language", "scope.language.non_latin_script")
            else:
                st.covered.append((cs, ce))
            return
        if script == "diacritic":
            st.diacritic_clauses.append((cs, ce))
        lang = "en"
    else:
        lang = R.lang_of(seg)
    # "Would you delete the cluster if I asked?" — a modal question about a side-effecting operation is hypothetical when it
    # carries a hypothetical condition or adverb; decided after the trigger is known (see step 2)
    hypo = R.HYPO_PREFIX_RE.match(seg)
    is_question = "?" in text[ce:ce + 3]
    mw = R.MEANWHILE_RE.match(seg)
    st.immediate_clause = bool(mw) and bool(st.sent_conditions.get(c.sent))
    i = _strip_prefixes(seg)
    if mw and mw.end() > i:
        i = mw.end() + _strip_prefixes(seg[mw.end():])
    if hypo and is_question and hypo.end() > i:
        i = hypo.end()
    ma = R.APPROVAL_NP_CONDITION_RE.match(seg[i:] + " ")     # "After my approval, change the config" → an *after* condition over the sentence
    if ma:
        if not seg[i + ma.end():].strip(" \t\r\n.,;:—–-"):    # the clause *is* the condition ("After your approval, …" cut at the comma)
            _emit_condition(st, c, "after", cs + i, ce, f"{lang}.condition.after.approval_np", sentence_level=True)
            return
        _emit_condition(st, c, "after", cs + i, cs + i + ma.end(), f"{lang}.condition.after.approval_np", sentence_level=True)
        i += ma.end()
        i += _strip_prefixes(seg[i:])

    # 0. "otherwise …" opens the complement branch of the last condition; a condition-initial clause is a Condition node
    me = R.ELSE_START_RE.match(seg[i:])
    if me:
        _emit_condition(st, c, "else", cs + i, cs + i + me.end(), f"{lang}.condition.else", negates=st.last_cond_id, sentence_level=True)
        i += me.end()
        i += _strip_prefixes(seg[i:])                  # "інакше просто підтверди …" — politeness after the else-marker
    mc = R.CONDITION_START_RE.match(seg[i:])
    mt = R.UNTIL_THEN_RE.match(seg[i:])
    if mt and _match_action(seg[i + mt.end():], interrogative=False) is not None:
        # "until then show a summary" — the anaphoric marker is the whole condition; the imperative that follows is a governed objective
        _emit_condition(st, c, "until", cs + i, cs + i + mt.end(), f"{lang}.condition.until.anaphoric", sentence_level=True)
        i += mt.end()
        mc = None
    if mc:
        kind = _condition_kind(mc.group(0).strip(" ,\t\n").lower())
        body = seg[i + mc.end():]
        if kind in ("after", "before"):
            hit = _match_action(body, interrogative=False, gerund=True)
            # "After listing the ports, …" — a requested, non-mutating step with an explicit object stays an objective
            if hit and hit[1] == "gerund" and ACTION_CLASS[hit[0]] not in _MUTATING and body[hit[2]:].strip():
                sa, sb = trim(text, cs + i, cs + i + mc.end())
                _emit_objective(st, c, cs, ce, lang, hit, cs + i + mc.end(), subord=(kind, (sa, sb)))
                return
        if kind is not None and (kind not in ("after", "before") or R.CLAUSE_AFTER_MARKER_RE.match(body)):
            ment = _mentioned_action(body)
            _emit_condition(st, c, kind, cs + i, ce, f"{lang}.condition.{kind}", mentioned=ment[0] if ment else None, sentence_level=True)
            if c.joiner in ("sequence", "alt") and c.marker is not None:     # ", then if they pass, deploy" → the link belongs to "deploy"
                st.pending_joiner[c.sent] = (c.joiner, c.marker)
            return

    leading: list[tuple[int, int, str]] = []          # "In one sentence, …" / "As a table, …" / "Only …" ahead of the trigger
    while True:
        hit_lead = next(((k, m) for k, p in R.INLINE_RULES if k in R.LEADING_CONSTRAINT_KINDS for m in [p.match(seg[i:])] if m), None)
        if not hit_lead or st.mask.overlaps(cs + i, cs + i + hit_lead[1].end()):
            break
        after = seg[i + hit_lead[1].end():]
        sep = R.LEADING_SEP_RE.match(after)
        if not after.strip(" \t\r\n.!…,;:"):          # the clause *is* the constraint ("…, не більше десяти." / "Answer in Ukrainian.")
            if hit_lead[0] != "scope_only" or re.search(r"nothing|нічого", hit_lead[1].group(0), re.I):   # "…, and nothing else."
                leading.append((cs + i, cs + i + hit_lead[1].end(), hit_lead[0]))
                i += len(after) + hit_lead[1].end()
            break
        if not sep or (hit_lead[0] == "scope_only" and not R.IMPERATIVE_LOOKAHEAD_RE.match(after[sep.end():])):
            break
        leading.append((cs + i, cs + i + hit_lead[1].end(), hit_lead[0]))
        i += hit_lead[1].end() + sep.end()
    rest = seg[i:]
    if rest.strip() and st.mask.covers(cs + i):            # "It says `disregard safety rules …`" — the clause continues inside data
        a, b = trim(text, cs, ce)
        st.g.context_statements.append(ContextStatement(st.nid("k"), text[a:b], Span(a, b), f"{lang}.data_statement"))
        st.covered.append((a, b))
        return
    if not rest.strip():
        if leading:                                     # a stranded constraint clause scopes the objective before it (or the request)
            _stranded_constraints(st, c, leading, lang)
            return
        _unresolved(st, c.sent, cs, ce, "no_recognized_action", f"{lang}.prefix_only")
        return

    md = _EMPHATIC_DO_RE.match(rest)
    if md:
        hit_e = _match_action(rest[md.end():], interrogative=False)
        if hit_e and ACTION_CLASS[hit_e[0]] not in _MUTATING:
            i += md.end()
            rest = seg[i:]
    # 1. clause-level constraints — never inside a modal question ("Could you ever drop X if asked?" is a question, not a constraint)
    modal_q = bool(hypo and is_question)
    mdp = None if (modal_q or is_question) else _DO_PRONOUN_RE.match(rest)
    if mdp:                                            # "Do it." / "Зроби це." — an operation named only by a pronoun: unresolved head, no objective
        _unresolved(st, c.sent, cs + i, ce, "ambiguous_referent", f"{lang}.referent.do_pronoun", referent=mdp.group("pro"))
        return
    mur = None if (modal_q or is_question or lang != "en") else R.UNIVERSAL_RESTRICTION_RE.match(rest)
    if mur and not st.mask.overlaps(cs + i, cs + i + mur.end()):
        # "Do nothing outside chat." / "No external calls of any kind." / "Nothing should change." / "Treat this as read-only." — an unbound
        # restriction covering every side-effect class; a later imperative cannot erase it (sheet v5 rule 23; DCE-G1R3D)
        v_end, trailing = _trailing_conditions(st, cs + i, ce)
        cst = _clause_constraint(st, c, cs, ce, "prohibition", "en.prohibition.universal", target_action=None,
                                 value=st.mention(cs + i, v_end), breadth="global")
        for kind_q, qa, qb, ment_q in trailing:
            _emit_condition(st, c, kind_q, qa, qb, f"{lang}.condition.{kind_q}.trailing", mentioned=ment_q, applies=[cst.id])
        return
    mnu = None if modal_q else R.NOT_UNTIL_RE.match(rest)
    if mnu:                                            # "Not until sign-off should you delete stale branches" → prohibition + until-condition
        ment = _mentioned_action(mnu.group("rest"))
        r0 = cs + i + mnu.start("rest")
        obj = st.mention(r0 + ment[1], ce) if ment else st.mention(r0, ce)
        t_act = ment[0] if ment else None
        cst = _clause_constraint(st, c, cs, ce, "prohibition", f"{lang}.prohibition.not_until", target_action=t_act, value=st.mention(r0, ce),
                                 target_object=obj, breadth=_breadth(obj))
        if t_act:
            st.last_mention = (t_act, obj)
        _emit_condition(st, c, mnu.group("kind").lower(), cs + i + mnu.start("cond"), cs + i + mnu.end("cond"), f"{lang}.condition.{mnu.group('kind').lower()}.not_until",
                        applies=[cst.id])
        return
    mg = None if modal_q else R.NO_GERUND_RE.match(rest)
    if mg:                                             # "No touching live cluster settings until approval"
        ment = _mentioned_action(mg.group("ger") + " " + mg.group("obj"))
        if ment:
            v_end, trailing = _trailing_conditions(st, cs + i + mg.start("ger"), ce)
            obj = st.mention(cs + i + mg.start("ger") + ment[1], v_end)
            cst = _clause_constraint(st, c, cs, ce, "prohibition", f"{lang}.prohibition.no_gerund", target_action=ment[0], value=st.mention(cs + i + mg.start("ger"), v_end),
                                     target_object=obj, breadth=_breadth(obj))
            st.last_mention = (ment[0], obj)
            for kind_q, qa, qb, ment_q in trailing:
                _emit_condition(st, c, kind_q, qa, qb, f"{lang}.condition.{kind_q}.trailing", mentioned=ment_q, applies=[cst.id])
            return
    md_ = None if modal_q else R.DELIVERABLES_RE.match(rest)
    if md_ and not st.mask.overlaps(cs + i, cs + i + md_.start("list")):   # "Give two separate outputs: a risk table and an action checklist"
        l0 = cs + i + md_.start("list")
        parts, pos = [], l0
        for sm in R.DELIVERABLE_SPLIT_RE.finditer(text, l0, ce):
            if st.mask.overlaps(sm.start(), sm.end()):
                continue
            parts.append((pos, sm.start())); pos = sm.end()
        parts.append((pos, ce))
        parts = [(a, b) for a, b in parts if text[a:b].strip(" .;,")]
        want = R.DELIVERABLE_COUNTS.get(md_.group("count").lower()) if md_.group("count") else None
        if want is not None and len(parts) < want:
            # "Two things: a risk table and a mitigation checklist" / "план, оцінку і коротку відповідь" — the declared count says the
            # last comma-part still holds two items: split it at its last bare "and"
            la, lb = parts[-1]
            ands = [sm for sm in R.DELIVERABLE_LAST_AND_RE.finditer(text, la, lb) if not st.mask.overlaps(sm.start(), sm.end())]
            if ands:
                parts = parts[:-1] + [(la, ands[-1].start()), (ands[-1].end(), lb)]
                parts = [(a, b) for a, b in parts if text[a:b].strip(" .;,")]
        if len(parts) >= 2:
            for a, b in parts:
                a, b = trim(text, a, b, strip_leading_punct=True)
                nm = R.NOMINAL_RE.match(text[a:b])
                act = R.NOMINAL_ACTION.get(nm.group("noun").lower()) if nm and nm.group("noun").lower() in R.NOMINAL_ACTION else "compose"
                _emit_objective(st, c, a, b, lang, (act, "nominal", 0), a)
            return
    mu = None if modal_q else R.UK_INF_NOT_NEEDED_RE.match(rest)
    if mu and not st.mask.overlaps(cs + i, cs + i + mu.end()):
        # "Виконувати нічого не треба" / "Застосовувати його не треба" — infinitive-first impersonal prohibition
        hit = _match_action(mu.group("inf"), interrogative=False, gerund=True)
        act = hit[0] if hit else None
        if act is None:
            for action, pat in R.MENTION_FORMS:
                if pat.match(mu.group("inf")):
                    act = action; break
        if act is not None:
            og = "obj" if mu.group("obj") else ("obj0" if mu.group("obj0") else None)
            null_obj = og is None or mu.group(og).lower().startswith(("нічого", "жодних"))
            obj = None if null_obj else st.mention(cs + i + mu.start(og), cs + i + mu.end(og))
            v_end, trailing = _trailing_conditions(st, cs + i + mu.end(), ce)
            st.last_mention = (act, obj)
            cst = _clause_constraint(st, c, cs, ce, "prohibition", f"{lang}.prohibition.infinitive_first", target_action=act,
                                     value=st.mention(cs + i, v_end), target_object=obj, breadth="global" if null_obj else _breadth(obj))
            for kind_q, qa, qb, ment_q in trailing:
                _emit_condition(st, c, kind_q, qa, qb, f"{lang}.condition.{kind_q}.trailing", mentioned=ment_q, applies=[cst.id])
            return
    m = None if modal_q else R.PROHIBITION_START_RE.match(rest)
    if m and not R.WHETHER_OR_NOT_RE.match(rest):
        marker = m.group(0).strip().lower()
        v0 = cs + i + m.end()
        v_end, trailing = _trailing_conditions(st, v0, ce)
        value_text = text[v0:v_end]
        ment = _mentioned_action(value_text)
        kind = "exclusion" if marker in ("not", "without", "без") or (marker == "не" and R.UK_PARTICIPLE_RE.match(value_text)) else "prohibition"
        passive = R.PASSIVE_PROHIBITION_RE.match(value_text)        # "not a single file may be deleted" → remove / global
        do_so = kind == "prohibition" and R.DO_SO_RE.match(value_text)   # "Do not do so" → the operation last named in the utterance
        coord_actions: list[str] = []
        if passive:
            kind, ment = "prohibition", (_participle_action(passive.group("part")), len(value_text))
            obj = None
        elif do_so:
            ment = (st.last_mention[0], len(value_text)) if st.last_mention else None
            obj = st.last_mention[1] if st.last_mention else None
        elif ment:                                 # recognised verb → object is what follows it
            obj = st.mention(v0 + ment[1], v_end)
            ment, obj = _coordinated_prohibition(st, text, v0 + ment[1], v_end, ment, obj, coord_actions)   # "save or run it" (G1R3C)
        elif kind == "prohibition" and marker in _NOMINAL_NEG_MARKERS and value_text.strip():   # "жодних команд" → the noun phrase
            obj = st.mention(v0, v_end)
        elif kind == "prohibition" and value_text.split():   # "do not assume RAM is bottleneck": first word is the verb
            w_end = v0 + len(value_text) - len(value_text.lstrip()) + len(value_text.split(None, 1)[0])
            obj = st.mention(w_end, v_end)
            ment, obj = _coordinated_prohibition(st, text, w_end, v_end, None, obj, coord_actions)   # "never push or merge to main" (G1R3C)
        elif kind == "exclusion" and value_text.strip():     # "not a migration" / "without screenshots": the nominal is the excluded object
            obj = st.mention(v0, v_end)
        else:
            obj = None
        null_obj = kind == "prohibition" and (R.NULL_OBJECT_RE.match(value_text) or marker.startswith(("нічого", "нікого", "ніколи нічого")))   # "нічого не роби" / "Stop nothing" → global
        if null_obj and not ment and marker in ("stop", "stop doing"):
            ment = ("run", 0)
        if ment is None and obj is not None and not do_so:     # "without changes" / "без змін" → the noun names an operation class
            noun_act = _restricted_noun_action(obj.text)
            if noun_act:
                ment = (noun_act, 0)
        breadth = "global" if (passive or null_obj) else (_breadth(obj) if (ment or obj) else None)
        if do_so and ment and obj is None:
            breadth = "global"
        if ment:
            st.last_mention = (ment[0], None if (null_obj or do_so) else obj)
        cst = _clause_constraint(st, c, cs, ce, kind, f"{lang}.{kind}.clause", target_action=ment[0] if ment else None,
                                 value=st.mention(v0, v_end), target_object=None if null_obj else obj, breadth=breadth)
        csts = [cst]
        for extra in coord_actions:                # one constraint per coordinated prohibited verb (sheet v4 rule 16)
            csts.append(_clause_constraint(st, c, cs, ce, kind, f"{lang}.{kind}.clause.coordinated", target_action=extra,
                                           value=st.mention(v0, v_end), target_object=None if null_obj else obj, breadth=breadth))
        for kind_q, qa, qb, ment_q in trailing:
            _emit_condition(st, c, kind_q, qa, qb, f"{lang}.condition.{kind_q}.trailing", mentioned=ment_q, applies=[x.id for x in csts])
        return
    m = None if modal_q else R.NO_NOUN_RE.match(rest)
    if m:
        noun = m.group(1).strip().lower()
        passive = R.PASSIVE_PROHIBITION_RE.match(" " + m.group(1))   # "No table must be dropped" → remove / global
        if passive:
            _clause_constraint(st, c, cs, ce, "prohibition", f"{lang}.prohibition.passive", target_action=_participle_action(passive.group("part")),
                               value=st.mention(cs + i, ce), breadth="global")
            return
        obj = st.mention(cs + i + m.start(1), cs + i + m.end(1))
        mto = R.NO_NOUN_TO_RE.match(m.group(1).strip())
        if mto:                                     # "No changes to the production database" → modify / the production database (G1R3C)
            t_act = R.NOMINAL_ACTION.get(mto.group("noun").lower()) or _restricted_noun_action(mto.group("noun"))
            o0 = cs + i + m.start(1) + (len(m.group(1)) - len(m.group(1).lstrip())) + mto.start("obj")
            tgt = st.mention(o0, o0 + len(mto.group("obj")))
            if t_act:
                st.last_mention = (t_act, tgt)
            _clause_constraint(st, c, cs, ce, "prohibition", f"{lang}.prohibition.nominal.to", target_action=t_act,
                               value=obj, target_object=tgt, breadth=_breadth(tgt))
            return
        t_act = R.NOMINAL_ACTION.get(noun) or _restricted_noun_action(noun)     # "No recommendations" → recommend; "No shell commands" → run
        if t_act:
            st.last_mention = (t_act, obj)
        _clause_constraint(st, c, cs, ce, "prohibition", f"{lang}.prohibition.nominal", target_action=t_act,
                           value=obj, target_object=obj, breadth=_breadth(obj))     # nominal "No shell commands" keeps the published G1R convention (narrow; P14)
        return
    mp = R.NEG_SUBJECT_RE.match(rest) and R.PASSIVE_PROHIBITION_RE.match(rest)   # "Nothing may be executed on the host"
    if mp:
        _clause_constraint(st, c, cs, ce, "prohibition", f"{lang}.prohibition.passive", target_action=_participle_action(mp.group("part")),
                           value=st.mention(cs + i, ce), breadth="global")
        return
    mna = None if modal_q else R.NEG_ADJ_PROHIBITION_RE.match(rest)              # "Nothing destructive, obviously." / "Нічого незворотного."
    if mna:
        _clause_constraint(st, c, cs, ce, "prohibition", f"{lang}.prohibition.negative_adjective", target_action=None,
                           value=st.mention(cs + i, cs + i + mna.end()), breadth="global")
        return
    msp = None if modal_q else R.SUBJECT_PASSIVE_NEG_RE.match(rest)              # "prod must not be modified" / "база не повинна змінюватися"
    if msp:
        act = _participle_action(msp.group("part")) or _mentioned_action(msp.group("part").lower().replace("тися", "ти").replace("тись", "ти"))
        act = act[0] if isinstance(act, tuple) else act
        if act:
            a0 = cs + i + msp.start("subj")
            _clause_constraint(st, c, cs, ce, "prohibition", f"{lang}.prohibition.subject_passive", target_action=act,
                               target_object=st.mention(a0, a0 + len(msp.group("subj"))), breadth="narrow")
            return
    if not modal_q and lang == "en":                                            # DCE-G1R3C English prohibition grammar
        msa = R.SUBJECT_ACTIVE_NEG_RE.match(rest)                               # "The migration bundle must not change."
        if msa:
            verb = msa.group("verb").lower()
            act = R.SUBJECT_ACTIVE_VERB_ACTION.get(verb) or _participle_action(verb.split()[-1])
            if act:
                a0 = cs + i + msa.start("subj")
                tgt = st.mention(a0, a0 + len(msa.group("subj")))
                st.last_mention = (act, tgt)
                _clause_constraint(st, c, cs, ce, "prohibition", "en.prohibition.subject_active", target_action=act,
                                   target_object=tgt, breadth="narrow")
                return
        mpp = R.PREDICATIVE_PROHIBITION_RE.match(rest)                          # "Changes to the firewall are forbidden."
        if mpp:
            act = R.NOMINAL_ACTION.get(mpp.group("noun").lower()) or _restricted_noun_action(mpp.group("noun"))
            tgt = st.mention(cs + i + mpp.start("obj"), cs + i + mpp.end("obj")) if mpp.group("obj") else None
            if act:
                st.last_mention = (act, tgt)
            _clause_constraint(st, c, cs, ce, "prohibition", "en.prohibition.predicative", target_action=act,
                               value=st.mention(cs + i, cs + i + mpp.end()), target_object=tgt, breadth=_breadth(tgt) if tgt else "global")
            return
        mol = R.SUBJECT_OFF_LIMITS_RE.match(rest)                               # "src/api.py is off-limits." / "prod is read-only"
        if mol:
            a0 = cs + i + mol.start("subj")
            tgt = st.mention(a0, a0 + len(mol.group("subj")))
            st.last_mention = ("modify", tgt)
            _clause_constraint(st, c, cs, ce, "prohibition", "en.prohibition.off_limits", target_action="modify",
                               value=st.mention(cs + i, cs + i + mol.end()), target_object=tgt, breadth="narrow")
            return
        mku = R.KEEP_UNTOUCHED_RE.match(rest)                                   # "Keep config.yaml as is" / "Leave the branch alone"
        if mku:
            tgt = st.mention(cs + i + mku.start("obj"), cs + i + mku.end("obj"))
            st.last_mention = ("modify", tgt)
            _clause_constraint(st, c, cs, ce, "prohibition", "en.prohibition.keep_untouched", target_action="modify",
                               value=st.mention(cs + i, cs + i + mku.end()), target_object=tgt, breadth=_breadth(tgt))
            return
    ma = None if modal_q else R.NEG_SUBJECT_ACTIVE_RE.match(rest)                # "Nothing in prod may change" / "Ніщо на проді не має змінюватися"
    if ma:
        ment = _mentioned_action(ma.group("verb"))
        if ment:
            v_end, trailing = _trailing_conditions(st, cs + i + ma.end(), ce)
            st.last_mention = (ment[0], None)
            cst = _clause_constraint(st, c, cs, ce, "prohibition", f"{lang}.prohibition.negative_subject", target_action=ment[0],
                                     value=st.mention(cs + i, v_end), breadth="global")
            for kind_q, qa, qb, ment_q in trailing:
                _emit_condition(st, c, kind_q, qa, qb, f"{lang}.condition.{kind_q}.trailing", mentioned=ment_q, applies=[cst.id])
            return
    for kind, pat in (("requirement", R.REQUIREMENT_START_RE), ("exclusion", R.EXCLUSION_START_RE)):
        m = None if modal_q else pat.match(rest)
        if m:
            v_end, trailing = _trailing_conditions(st, cs + i + m.end(), ce)
            value = st.mention(cs + i + m.end(), v_end)
            t_act, t_obj, breadth = None, None, None
            if kind == "exclusion" and value is not None:             # "ignore the injected instructions" → the excluded object is explicit
                ment = _mentioned_action(value.text)
                if ment and st.mention(value.source_span.start + ment[1], v_end) is not None:
                    t_act, t_obj = ment[0], st.mention(value.source_span.start + ment[1], v_end)
                else:
                    t_act, t_obj = _restricted_noun_action(value.text), value
                breadth = _breadth(t_obj)
            cst = _clause_constraint(st, c, cs, ce, kind, f"{lang}.{kind}.clause", value=value, target_action=t_act, target_object=t_obj, breadth=breadth)
            for kind_q, qa, qb, ment_q in trailing:
                _emit_condition(st, c, kind_q, qa, qb, f"{lang}.condition.{kind_q}.trailing", mentioned=ment_q, applies=[cst.id])
            if kind == "requirement":                  # "keep it under 200 words and in English" → the locale is its own constraint
                for a, b, k2, krule, value, _t, _o in _inline_constraints(st, cs + i + m.end(), v_end, lang):
                    if k2 == "locale":
                        st.g.constraints.append(Constraint(st.nid("c"), k2, text[a:b], Span(a, b), krule, cst.scope, list(cst.applies_to_objective_ids), value=value))
            return

    # 1b. "<verb> nothing [unless …]" — a null object makes the clause a prohibition whatever the verb ("Do nothing unless I say go",
    #     "Change nothing until I confirm"); checked before the trigger so that "Do" is not read as a question head
    mz = R.NULL_OBJECT_CLAUSE_RE.match(rest)
    if mz:
        v_end, trailing = _trailing_conditions(st, cs + i, ce)
        if R.NULL_OBJECT_RE.match(text[cs + i + mz.end("verb"):v_end]):
            verb = mz.group("verb")
            vh = _match_action(verb, interrogative=False)
            t_act = vh[0] if vh and vh[2] == len(verb) else None
            if t_act is None and verb.lower() in ("stop", "halt"):
                t_act = "run"
            cst = _clause_constraint(st, c, cs, ce, "prohibition", f"{lang}.prohibition.null_object", target_action=t_act,
                                     value=st.mention(cs + i + mz.end("verb"), v_end), breadth="global")
            if t_act:
                st.last_mention = (t_act, None)
            for kind_q, qa, qb, ment_q in trailing:
                _emit_condition(st, c, kind_q, qa, qb, f"{lang}.condition.{kind_q}.trailing", mentioned=ment_q, applies=[cst.id])
            return

    # 2. action trigger
    hit = _match_action(rest)
    rule_family = None
    if hit is None:
        nm = R.NOMINAL_RE.match(rest)
        if nm and nm.group("noun").lower() in R.NOMINAL_ACTION:
            hit, rule_family = _nominal_hit(nm), "nominal"
    if hit is not None:
        action, fam, trig_end = hit
        trig_word = _WORD_RE.search(rest[:trig_end] or " ")
        if fam == "imperative" and trig_word and trig_word.group(0).lower() in NOUNISH_VERBS and _DECL_AFTER_NOUNISH_RE.match(rest[trig_end:]):
            hit = None   # "Output files are missing" — declarative, not an instruction
        elif action == "extract" and fam == "imperative":      # "give me a detailed plan" / "provide a comparison of …" → the deliverable's action
            nm = R.NOMINAL_RE.match(rest)
            if nm and nm.end() >= trig_end and nm.group("noun").lower() in R.NOMINAL_ACTION:
                hit, rule_family = _nominal_hit(nm), "nominal"
        if hit is not None and hypo and is_question and ACTION_CLASS[hit[0]] in _MUTATING:
            # hypothetical question about a side-effecting operation → a judgement question; the operation is only *mentioned*
            v_end, trailing = _trailing_conditions(st, cs + i + hit[2], ce)
            hypothetical = bool(R.HYPO_ADVERB_RE.search(seg[:hypo.end()])) or any(
                k == "if" and R.HYPO_CONDITION_RE.match(text[qa:qb]) for k, qa, qb, _ in trailing)
            # "Would you deploy that code without checking the tests?" — *would* + a reproach clause is a question about conduct, not a request;
            # "Could you restart the pods, please?" stays a request
            if not hypothetical and (_WOULD_RE.match(seg) and not _POLITE_REQUEST_RE.search(seg) or _WITHOUT_GERUND_RE.search(seg)):
                hypothetical = True
            if hypothetical:
                st.last_mention = (hit[0], st.mention(cs + i + hit[2], v_end))
                _emit_objective(st, c, cs, ce, lang, ("assess", "interrogative", 0), cs, leading=leading, keep_mention=True)
                return
    if hit is None and lang == "uk":
        mo = _UK_OBJECT_FIRST_NEG_RE.match(rest)      # "інтеграційні тести не чіпай" — fronted object, negated imperative
        if mo:
            hv = _match_action(mo.group("verb"), interrogative=False)
            if hv and ACTION_CLASS[hv[0]] in _MUTATING:
                obj = st.mention(cs + i + mo.start("obj"), cs + i + mo.end("obj"))
                st.last_mention = (hv[0], obj)
                _clause_constraint(st, c, cs, ce, "prohibition", f"{lang}.prohibition.object_first", target_action=hv[0],
                                   value=st.mention(cs + i, ce), target_object=obj, breadth=_breadth(obj))
                return
    if hit is None and hypo and is_question:
        # "Ти б видалив кластер, якби я попросив?" — the verb form is not a trigger but a *mention* of a side-effecting operation
        off = max(i, hypo.end())                     # politeness prefixes and the modal head may overlap
        v_end, trailing = _trailing_conditions(st, cs + off, ce)
        ment = _mentioned_action(seg[off:v_end - cs])
        if ment and ACTION_CLASS[ment[0]] in _MUTATING and (bool(R.HYPO_ADVERB_RE.search(seg[:hypo.end()])) or any(
                k == "if" and R.HYPO_CONDITION_RE.match(text[qa:qb]) for k, qa, qb, _ in trailing)):
            st.last_mention = (ment[0], st.mention(cs + off + ment[1], v_end))
            _emit_objective(st, c, cs, ce, lang, ("assess", "interrogative", 0), cs, leading=leading, keep_mention=True)
            return
    if hit is None:
        # "Screenshots are not needed." / "Creating tickets is not part of this task." / "I don't want a rewrite." → nominal prohibition
        mn = R.DECL_NEG_RE.match(rest) or R.DONT_WANT_RE.match(rest)
        if mn:
            na, nb = cs + i + mn.start("noun"), cs + i + mn.end("noun")
            art = re.match(r"(?:a|an|any|the|some)\s+", text[na:nb], re.I)
            core = na + (art.end() if art else 0)
            noun_text = text[core:nb]
            ment = _mentioned_action(noun_text)
            if ment and st.mention(core + ment[1], nb) is not None:   # "creating tickets" → create / "tickets"
                t_act, obj = ment[0], st.mention(core + ment[1], nb)
            elif ment:                                 # "a rewrite" — a deverbal noun: the action *and* the object
                t_act, obj = ment[0], st.mention(na, nb)
            else:
                t_act, obj = _restricted_noun_action(noun_text) or (R.NOMINAL_ACTION.get(noun_text.lower().split()[-1]) if noun_text.split() else None), st.mention(na, nb)
            if t_act:
                st.last_mention = (t_act, obj)
            _clause_constraint(st, c, cs, ce, "prohibition", f"{lang}.prohibition.declarative", target_action=t_act,
                               value=st.mention(na, nb), target_object=obj, breadth=_breadth(obj) if (ment or obj) else "global")
            return
        ml = R.LABEL_ONLY_RE.match(rest)
        if ml and st.mask.covers(cs + i + ml.end()) and st.mask.covers(max(cs + i + ml.end(), trim(text, cs, ce)[1] - 1)):
            a, b = trim(text, cs, ce)                  # "Text in quotes: "…"" — the payload is data, never an instruction
            st.g.context_statements.append(ContextStatement(st.nid("k"), text[a:b], Span(a, b), f"{lang}.declarative.labelled_quote"))
            st.covered.append((a, b))
            return
        if R.DECLARATIVE_RE.match(rest):
            a, b = trim(text, cs, ce)
            st.g.context_statements.append(ContextStatement(st.nid("k"), text[a:b], Span(a, b), f"{lang}.declarative"))
            st.covered.append((a, b))
            return
        if R.ANY_LETTER_RE.search(rest) and not (R.LATIN_RE.search(rest) or R.CYRILLIC_RE.search(rest)):
            _unresolved(st, c.sent, cs, ce, "unsupported_script", "script.unsupported")
        else:                                          # an unknown verb still carries its explicit qualifiers ("hold until I say go before executing anything")
            if leading:                                # "…, не більше двадцяти рядків, відсортовану за розміром" — keep the constraints, type the rest
                _stranded_constraints(st, c, leading, lang)
            v_end, trailing = _trailing_conditions(st, cs + i, ce)
            uid = _unresolved(st, c.sent, cs + i if leading else cs, v_end if trailing else ce, "no_recognized_action", f"{lang}.no_trigger")
            for kind_q, qa, qb, ment_q in trailing:
                _emit_condition(st, c, kind_q, qa, qb, f"{lang}.condition.{kind_q}.trailing", mentioned=ment_q, applies=[uid])
        return
    _emit_objective(st, c, cs, ce, lang, hit if rule_family is None else (hit[0], "nominal", hit[2]), cs + i, leading=leading)


def _emit_objective(st: _State, c: _Clause, cs: int, ce: int, lang: str, hit: tuple[str, str, int], content_start: int, *,
                    leading: Optional[list[tuple[int, int, str]]] = None, subord: Optional[tuple[str, tuple[int, int]]] = None,
                    keep_mention: bool = False) -> None:
    text = st.text
    action, fam, trig_end = hit
    rule = f"{lang}.{fam}.{action}"
    t0 = content_start + trig_end
    trigger = st.mention(content_start, t0) if trig_end > 0 else None
    t_end, trailing = _trailing_conditions(st, t0, ce)
    target_a, target_b = trim(text, t0, t_end, strip_leading_punct=True)
    io = _INDIRECT_OBJECT_RE.match(text, target_a, target_b)       # "Write me a script" → the object is "a script"
    if io and io.end() < target_b:
        target_a = io.end()

    # 3. inline constraints inside the target; only those after the target's head word are trimmed off the target
    inline = _inline_constraints(st, target_a, target_b, lang)
    for cst in inline:                                  # "Show only the failed tests" → the adverb is not part of the object
        if cst[2] == "scope_only" and cst[0] == target_a:
            target_a = min(cst[0] + len(text[cst[0]:cst[1]].split(None, 1)[0]), target_b)
    head_end = _head_end(text, target_a, target_b)
    tb = target_b
    for cst in sorted(inline, key=lambda x: -x[0]):
        _, tb_trim = trim(text, target_a, tb)
        if cst[1] >= tb_trim and cst[0] >= head_end:
            tb = cst[0]
    target_a, target_b = trim(text, target_a, tb, strip_leading_punct=True)
    target = Mention(text[target_a:target_b], Span(target_a, target_b)) if target_b > target_a else None
    if target is not None and R.NULL_OBJECT_RE.match(target.text):   # "Recommend nothing." → prohibition of the action
        _clause_constraint(st, c, cs, ce, "prohibition", f"{lang}.prohibition.null_object", target_action=action, value=target, breadth="global")
        st.last_mention = (action, None)
        return
    if target is not None and ACTION_CLASS[action] in _MUTATING and R.VAGUE_OBJECT_RE.match(target.text) and not st.mask.covers(target_a):
        _unresolved(st, c.sent, cs, ce, "vague_object", f"{lang}.vague_object")       # "Do something with the queue" / "Зроби щось із чергою"
        return
    neg = R.NEG_OBJECT_RE.match(target.text) if target is not None else None
    if neg and not st.mask.covers(target_a):                          # "Run no scripts" / "Delete no files" / "Execute zero commands" → prohibition
        obj = st.mention(target_a + neg.start("noun"), target_a + neg.end("noun"))
        if ACTION_CLASS[action] not in _MUTATING and obj is not None:        # "open no connections" — the noun names the operation class, not "show"
            action = _restricted_noun_action(obj.text) or action
        cst = _clause_constraint(st, c, cs, ce, "prohibition", f"{lang}.prohibition.negative_object", target_action=action, value=target,
                                 target_object=obj, breadth=_class_breadth(obj))
        st.last_mention = (action, obj)
        for kind_q, qa, qb, ment_q in trailing:
            _emit_condition(st, c, kind_q, qa, qb, f"{lang}.condition.{kind_q}.trailing", mentioned=ment_q, applies=[cst.id])
        return
    if ACTION_CLASS[action] in _MUTATING and target is not None:
        # "set RUN_MODE=dry-run in an example response" / "write it in your answer" — the artefact lives in the reply → compose
        ra = R.REPLY_ARTEFACT_RE.search(target.text)
        if ra and not st.mask.covers(target_a + ra.start()) and not _REPLY_ARTEFACT_NOT_RE.match(target.text, ra.end()):
            action, rule = "compose", f"{lang}.{fam}.compose.reply_artefact"
    if action == "compose" and target is not None and fam in ("imperative", "nominal"):
        # "Create a Markdown note at docs/runbook.md" — a named persisted destination makes the artefact a file, not answer text
        pd = R.PERSIST_DESTINATION_RE.search(target.text)
        if pd and pd.group(0).split()[0].lower() in ("in", "у", "в") and re.search(r"\b(?:for|of|about|regarding|describing|covering|on|для|про|щодо|стосовно)\s+(?:the|this|that|a|an|our|my|цього|цієї|цих)?\b", target.text[: pd.start()], re.I):
            pd = None                                  # "a unified diff for the change to the retry logic in client.py" — "in" locates the subject, not a destination
        if pd and not R.REPLY_ARTEFACT_RE.search(target.text):
            action, rule = "create", f"{lang}.{fam}.create.persisted_artefact"
    second: Optional[tuple[int, int, str]] = None
    if action == "compose" and target is not None and fam in ("imperative", "nominal"):
        # "a table of endpoints and, separately, a list of risks" → two deliverables
        cm = R.COORD_ARTEFACT_RE.match(target.text)
        if cm and not st.mask.overlaps(target_a + cm.start("sep"), target_a + cm.end("sep")):
            second = (target_a + cm.start("second"), target_b, "compose")
            target_a, target_b = trim(text, target_a, target_a + cm.end("first"))
            target = Mention(text[target_a:target_b], Span(target_a, target_b))
            ce = target_b

    # 4. references
    refs, head_unresolved = _references(st, target, c.sent)
    if head_unresolved is not None:
        uid = _unresolved(st, c.sent, cs, ce, "ambiguous_referent", f"{lang}.referent.head", referent=head_unresolved)
        for kind_q, qa, qb, ment_q in trailing:
            _emit_condition(st, c, kind_q, qa, qb, f"{lang}.condition.{kind_q}.trailing", mentioned=ment_q, applies=[uid])
        return

    oid = st.nid("o")
    obj = Objective(oid, action, ACTION_CLASS[action], text[cs:ce], Span(cs, ce), rule, trigger=trigger, target=target, references=refs)
    st.g.objectives.append(obj)
    st.covered.append((cs, ce))
    st.last_obj_sent[c.sent] = oid
    if not keep_mention and ACTION_CLASS[action] in _MUTATING:   # only side-effecting operations are what "do not do that" can refer to
        st.last_mention = (action, target)
    st.govern(c.sent, oid)
    for cst in st.pending_cst.pop(c.sent, []):     # "Ignore warnings and list errors" → the exclusion scopes the objective that follows
        if cst.kind != "prohibition":
            cst.scope, cst.applies_to_objective_ids = "objective", [oid]
    lead_csts = [(a, b, kind, f"{lang}.{kind}.leading", _constraint_value(st, a, b, kind), None, None) for a, b, kind in leading or []]
    for a, b, kind, krule, value, t_act, t_obj in lead_csts + inline:
        cid = st.nid("c")
        breadth = _breadth(t_obj) if kind in ("prohibition", "exclusion") and (t_act or t_obj) else None
        st.g.constraints.append(Constraint(cid, kind, text[a:b], Span(a, b), krule, "objective", [oid], target_action=t_act, value=value,
                                           target_object=t_obj, breadth=breadth))
        if kind == "format" and obj.output_shape is None:
            obj.output_shape = Mention(text[a:b], Span(a, b))
    for r in refs:
        if r.status == "unresolved":
            st.g.unresolved.append(Unresolved(st.nid("u"), "ambiguous_referent", r.text, r.source_span, f"{lang}.referent.inline", referent=r.text, objective_id=oid))
    for kind_q, qa, qb, ment_q in trailing:
        _emit_condition(st, c, kind_q, qa, qb, f"{lang}.condition.{kind_q}.trailing", mentioned=ment_q, applies=[oid])

    # 5. explicit ordering / alternatives
    prev = next((o for o in reversed(st.g.objectives) if o.id != oid), None)
    joiner, marker = c.joiner, c.marker
    if joiner == "cond" and c.sent in st.pending_joiner:        # inherited from the condition clause that opened this one
        joiner, marker = st.pending_joiner.pop(c.sent)
    if joiner == "sequence" and marker is not None and prev is not None:
        ma, mb = marker
        st.g.links.append(Link(st.nid("l"), "depends_on", oid, prev.id, text[ma:mb], Span(ma, mb), f"{lang}.sequence.marker"))
    if joiner == "alt" and marker is not None and prev is not None and st.last_obj_sent.get(c.sent) == oid:
        ma, mb = marker
        st.g.links.append(Link(st.nid("l"), "alternative_to", oid, prev.id, text[ma:mb], Span(ma, mb), f"{lang}.alternative.marker"))
    if st.pending_after is not None and st.pending_after[0] != oid:
        pid, (sa, sb) = st.pending_after
        st.g.links.append(Link(st.nid("l"), "depends_on", oid, pid, text[sa:sb], Span(sa, sb), f"{lang}.sequence.subordinator_after"))
        st.pending_after = None
    if st.pending_before is not None and st.pending_before[0] != oid:
        pid, (sa, sb) = st.pending_before
        st.g.links.append(Link(st.nid("l"), "depends_on", pid, oid, text[sa:sb], Span(sa, sb), f"{lang}.sequence.subordinator_before"))
        st.pending_before = None
    if subord is not None:
        kind, span = subord
        if kind == "after":
            st.pending_after = (oid, span)
        else:
            st.pending_before = (oid, span)
    if second is not None:                       # the coordinated second deliverable is its own objective (no link: same request)
        sa, sb, s_action = second
        sa, sb = trim(text, sa, sb, strip_leading_punct=True)
        if sb > sa:
            _emit_objective(st, _Clause(sa, sb, c.sent, "coord"), sa, sb, lang, (s_action, "nominal", 0), sa)


def _nominal_hit(nm: "re.Match[str]") -> tuple[str, str, int]:
    """A nominal request → (action, 'nominal', trigger_end). For a composed deliverable the noun phrase itself is the object
    ("I need a migration plan" → compose / "a migration plan"); for the others the object follows the noun ("a summary of X" → X)."""
    action = R.NOMINAL_ACTION[nm.group("noun").lower()]
    return action, "nominal", (nm.start("np") if action == "compose" else nm.end())


def _restricted_noun_action(noun: str) -> Optional[str]:
    """'shell commands' → run, 'changes' → modify, … (articles/quantifiers stripped; full phrase first, then the last two / one words)."""
    noun = _TEMPORAL_TAIL_RE.sub("", noun.strip())                     # "deploys today" → "deploys"
    head = _HEAD_BEFORE_PREP_RE.match(noun)                              # "changes to the code" → "changes"; "the comments in the script" → "the comments"
    if head and head.group(1).strip().lower() != noun.strip().lower():
        return _restricted_noun_action(head.group(1))
    words = [w for w in re.findall(r"[^\W\d_]+", noun.lower()) if w not in ("the", "a", "an", "any", "all", "some", "further", "more", "additional", "other", "жодних", "жодні", "будь-яких", "усіх", "всіх")]
    for probe in (" ".join(words), " ".join(words[-2:]), words[-1] if words else ""):
        if probe in R.RESTRICTED_NOUN_ACTION:
            return R.RESTRICTED_NOUN_ACTION[probe]
    return None


def _constraint_value(st: _State, a: int, b: int, kind: str) -> Optional[Mention]:
    """Operand of a format/locale/cardinality phrase: the shape after its preposition, or the number inside the match."""
    text = st.text
    if kind in ("format", "locale"):
        parts = text[a:b].split(None, 1)
        return st.mention(a + len(parts[0]), b) if len(parts) == 2 else None
    if kind == "cardinality":
        nums = list(R.CARD_NUMBER_RE.finditer(text, a, b))
        return st.mention(nums[-1].start(), nums[-1].end()) if nums else None
    if kind == "ordering":                            # "sorted by severity" / "відсортовану за розміром" → the sort key
        key = re.search(r"\s(?:by|за)\s+(\S+)\s*$", text[a:b], re.I)
        return st.mention(a + key.start(1), a + key.end(1)) if key else None
    return None


def _stranded_constraints(st: _State, c: _Clause, leading: list[tuple[int, int, str]], lang: str) -> None:
    for a, b, kind in leading:
        _clause_constraint(st, c, a, b, kind, f"{lang}.{kind}.clause", value=_constraint_value(st, a, b, kind))


def _head_end(text: str, a: int, b: int) -> int:
    """Offset just after the first content word of [a, b) (a word that is not a determiner/preposition); b if none."""
    for m in _WORD_RE.finditer(text, a, b):
        if not R.ARTICLE_RE.match(m.group(0)):
            return m.end()
    return b


def _clause_constraint(st: _State, c: _Clause, cs: int, ce: int, kind: str, rule: str, *, target_action: Optional[str] = None,
                       value: Optional[Mention] = None, target_object: Optional[Mention] = None, breadth: Optional[str] = None) -> Constraint:
    prev = st.last_obj_sent.get(c.sent) if c.joiner else None
    scope, ids = ("objective", [prev]) if prev else ("request", [])
    cst = Constraint(st.nid("c"), kind, st.text[cs:ce], Span(cs, ce), rule, scope, ids, target_action=target_action, value=value,
                     target_object=target_object, breadth=breadth)
    st.g.constraints.append(cst)
    st.cst_sent[cst.id] = c.sent
    st.covered.append((cs, ce))
    st.govern(c.sent, cst.id)
    if prev is None:
        st.pending_cst.setdefault(c.sent, []).append(cst)
    return cst


def _unresolved(st: _State, sent: int, a: int, b: int, kind: str, rule: str, *, referent: Optional[str] = None) -> str:
    u = Unresolved(st.nid("u"), kind, st.text[a:b], Span(a, b), rule, referent=referent)
    st.g.unresolved.append(u)
    st.covered.append((a, b))
    st.govern(sent, u.id)
    return u.id


def _inline_constraints(st: _State, a: int, b: int, lang: str) -> list[tuple[int, int, str, str, Optional[Mention], Optional[str], Optional[Mention]]]:
    """→ [(start, end, kind, rule, value, target_action, target_object)] for constraint phrases inside a target."""
    text = st.text
    hits: list[tuple[int, int, str]] = []
    wh = _WH_HEAD_RE.match(text, a, b)                 # the target is a wh-clause: numbers/"only" inside it describe the question
    for kind, pat in R.INLINE_RULES:
        for m in pat.finditer(text, a, b):
            if st.mask.overlaps(m.start(), m.end()) or any(h[0] <= m.start() < h[1] for h in hits):
                continue
            if (wh and kind in ("cardinality", "scope_only") and not R.INLINE_STOP_RE.search(text, a, m.start())
                    and not _REPLY_SHAPE_NOUN_RE.search(m.group(0))):   # "… in under ten bullets" still shapes the reply
                continue
            hits.append((m.start(), m.end(), kind))
    hits.sort()
    out = []
    for idx, (ms, me, kind) in enumerate(hits):
        end = hits[idx + 1][0] if idx + 1 < len(hits) else b
        stop = R.INLINE_STOP_RE.search(text, me, end)
        if stop and not st.mask.covers(stop.start()):
            end = stop.start()
        if kind in ("format", "locale"):               # "in one sentence and the details …" — the shape ends at the coordination
            stop = R.INLINE_COORD_STOP_RE.search(text, me, end)
            if stop and not st.mask.covers(stop.start()):
                end = stop.start()
        ca, cb = trim(text, ms, end)
        if cb <= ca:
            continue
        t_act, t_obj = None, None
        if kind in ("format", "locale", "cardinality"):
            value = _constraint_value(st, ms, me, kind)
        elif kind == "ordering" and me >= cb:          # the sort key is inside the match ("sorted by severity")
            value = _constraint_value(st, ms, me, kind)
        else:
            value = st.mention(me, cb)
            if kind == "exclusion" and value is not None:              # "without editing any files" → modify / "any files" / global
                ment = _mentioned_action(value.text)
                if ment:
                    t_act, t_obj = ment[0], st.mention(value.source_span.start + ment[1], cb)
                else:                                                  # "rather than direct fixes" / "без змін" → the nominal is the excluded object
                    t_act, t_obj = _restricted_noun_action(value.text), value
        out.append((ca, cb, kind, f"{lang}.{kind}.inline", value, t_act, t_obj))
    return out


def _references(st: _State, target: Optional[Mention], sent: int) -> tuple[list[Reference], Optional[str]]:
    if target is None:
        return [], None
    refs: list[Reference] = []
    head = R.PRONOUN_HEAD_RE.match(target.text)
    if head and R.EXPLETIVE_IT_RE.match(target.text[head.start():]):     # "it is safe to …" — expletive, not a referent
        head = None
    if head and _DEMONSTRATIVE_RE.match(target.text) and re.match(r"\s+(?![^\W\d_]+ly\b|швидше|швидко|негайно|зараз|знову|ще|також|теж|і\b|та\b|або\b|чи\b)[^\W\d_]", target.text[head.end():]):
        head = None                                     # "this runbook" / "цей Slack-чат" — a demonstrative + named noun is a definite NP, not a pronoun
    ante = st.antecedent(sent)
    each = st.for_each(sent)
    ctx = st.context.referents if st.context else ()
    seen: set[int] = set()
    matches = []
    if head:
        matches.append((target.source_span.start + head.start(), target.source_span.start + head.end(), True))
    for m in R.PRONOUN_ANY_RE.finditer(target.text):
        a = target.source_span.start + m.start()
        if head and a < target.source_span.start + head.end():
            continue
        if R.EXPLETIVE_IT_RE.match(target.text[m.start():]):
            continue
        matches.append((a, target.source_span.start + m.end(), False))
    head_unresolved = None
    for a, b, is_head in matches:
        if a in seen or st.mask.covers(a):
            continue
        seen.add(a)
        a2, b2 = trim(st.text, a, b)
        word = st.text[a2:b2].lower().split()[0] if b2 > a2 else ""
        demonstrative = word in ("this", "that", "these", "those", "the", "цей", "ця", "це", "ці", "той", "та", "те", "ті", "цього", "цієї", "цих", "тих")
        if demonstrative and len(st.block_ids) == 1:   # "Explain this snippet: ```…```" → the lone code/JSON/quote block
            status, to = "resolved_intra_utterance", st.block_ids[0]
        elif ante is not None:
            status, to = "resolved_intra_utterance", ante.id
        elif each is not None and not demonstrative:   # "For each service, state its port" → the iterated item
            status, to = "resolved_intra_utterance", each
        elif len(st.block_ids) == 1:
            status, to = "resolved_intra_utterance", st.block_ids[0]
        elif len(ctx) == 1:
            status, to = "resolved_context", ctx[0]
        else:
            status, to = "unresolved", None
            if is_head:
                head_unresolved = st.text[a2:b2]
        refs.append(Reference(st.text[a2:b2], Span(a2, b2), status, to))
    return refs, head_unresolved


# --- helpers --------------------------------------------------------------------------------------------------------

def _instruction_script(st: _State, a: int, b: int) -> str:
    """Script of the user-authored instruction text in [a, b): ``latin`` · ``diacritic`` (Latin with non-ASCII letters) ·
    ``non_latin``. Protected regions (code, quotes, URLs, paths, attachments) are data and are skipped."""
    diacritic = False
    for i in range(a, b):
        if st.mask.covers(i):
            continue
        ch = st.text[i]
        if not ch.isalpha():
            continue
        o = ord(ch)
        if o < 0x80:
            continue
        if (0xC0 <= o <= 0x24F or 0x1E00 <= o <= 0x1EFF) and ch not in "×÷":
            diacritic = True
            continue
        return "non_latin"
    return "diacritic" if diacritic else "latin"


def _language_hint(text: str) -> str:
    cyr, lat = bool(R.CYRILLIC_RE.search(text)), len(R.EN_FUNCTION_RE.findall(text)) >= 1
    if cyr and lat:
        return "mixed"
    if cyr:
        return "uk" if R.UKRAINIAN_RE.search(text) and not R.RUSSIAN_ONLY_RE.search(text) else "und"
    if R.LATIN_RE.search(text):
        return "en" if lat else "und"
    return "und"


def _stats(g: IntentGraph, clauses: int, chars_total: int, covered: Optional[list[tuple[int, int]]] = None) -> dict[str, int]:
    return {"clauses": clauses, "objectives": len(g.objectives), "constraints": len(g.constraints), "links": len(g.links),
            "unresolved": len(g.unresolved), "unresolved_references": sum(1 for o in g.objectives for r in o.references if r.status == "unresolved"),
            "context_statements": len(g.context_statements), "protected_regions": len(g.protected_regions), "conditions": len(g.conditions),
            "chars_covered": _union_len(covered or []), "chars_total": chars_total}


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
