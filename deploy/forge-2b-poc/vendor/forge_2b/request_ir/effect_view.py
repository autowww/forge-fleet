"""Effect-intent projection over a parsed ``RequestIR`` (DCE-G1R3A). Additive, read-only, deterministic.

The IntentGraph says *what* the user asked for in terms of an action vocabulary (``compose``, ``create``, ``run`` …). A
consumer that may cause side effects needs a different question answered: **what would satisfying this request do to the
world?** This module projects every objective onto one of five effect classes using only positive textual evidence:

* ``reply_only``            — the result lives in the answer (a plan, diff, SQL, script *as text*, a list, a judgement).
* ``artifact_write``        — a persisted file/document is created or modified at a grounded destination (path, file name,
                              "save it under docs/…", "to disk", "in the repository").
* ``environment_mutation``  — an application / repository / database / remote service / ticket / configuration is changed.
* ``command_execution``     — something is run, deployed, restarted, installed, applied, sent.
* ``unknown``               — the medium or the referent is not established by the text ("write a migration script",
                              "update the docs", "fix it"). **Unknown is the correct answer when evidence is missing;
                              a positive verb alone never establishes a side effect.**

Every ``EffectIntent`` carries the objective it came from, the evidence spans that decided the class, the conditions that
gate it (``conditional`` / ``approval_required`` — the *mention* of approval is never approval), and the constraints that
apply to it. Prohibitions are projected separately onto the same classes (``prohibited_effects``), so a consumer can see
"the text forbids command_execution" without needing the action vocabulary.

Nothing here authorizes anything. See :func:`effect_policy` in this module for the tri-state, deny-by-default reading
(``DENY`` / ``REQUIRE_RESOLUTION`` / ``TEXT_NOT_PROHIBITED``) — it has no ``ALLOW`` state by design.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Optional

from .schema import ACTION_CLASS, Constraint, Mention, Objective, RequestIR, Span, Unresolved
from . import policy_view as pv

__all__ = ["EffectIntent", "ProhibitedEffect", "EffectEvidence", "EffectProjection", "project_effects", "effect_policy",
           "REPLY_ONLY", "ARTIFACT_WRITE", "ENVIRONMENT_MUTATION", "COMMAND_EXECUTION", "UNKNOWN", "SIDE_EFFECT_CLASSES",
           "DENY", "REQUIRE_RESOLUTION", "TEXT_NOT_PROHIBITED", "PROJECTION_VERSION"]

PROJECTION_VERSION = "dce-g1r3d/0.3.1"

REPLY_ONLY, ARTIFACT_WRITE, ENVIRONMENT_MUTATION, COMMAND_EXECUTION, UNKNOWN = \
    "reply_only", "artifact_write", "environment_mutation", "command_execution", "unknown"
SIDE_EFFECT_CLASSES = (ARTIFACT_WRITE, ENVIRONMENT_MUTATION, COMMAND_EXECUTION)
DENY, REQUIRE_RESOLUTION, TEXT_NOT_PROHIBITED = "DENY", "REQUIRE_RESOLUTION", "TEXT_NOT_PROHIBITED"

_I = re.I | re.U
_W = r"(?<![\w'’-])"

# --- evidence lexicon ---------------------------------------------------------------------------------------------
# a grounded persisted destination: a path, a file name with extension, a file/document noun, "save … to disk / under docs/"
_FILE_EXT_RE = re.compile(r"(?<![\w/])[\w.-]+\.(?:ya?ml|json|ndjson|jsonl|parquet|avro|tgz|tsv|xlsx?|docx?|md|py|sh|bash|html?|txt|csv|cfg|conf|ini|toml|sql|js|ts|tsx|jsx|xml|env|lock|log|rst|tf|hcl|dockerfile|properties|gradle|ps1|rb|go|rs|java|kt|php|c|h|cpp|yml)\b", _I)
# "go/no-go", "yes/no", "blue/green", "and/or", "read/write", "I/O", "TCP/IP" are word pairs, not paths (DCE-G1R3D)
_PATH_RE = re.compile(r"(?<![\w.])(?!(?:go|no|yes|on|off|and|or|read|write|blue|green|pass|fail|input|output|client|server|tcp|ip|i|o|either|both|his|her|he|she|a|an|the|dev|prod|staging|test|qa|uat|ci|cd)/(?:no-go|no|yes|on|off|or|and|write|read|green|blue|fail|pass|output|input|server|client|ip|tcp|o|i|her|him|she|he|an|the|prod|dev|staging|test|qa|uat|cd|ci)\b(?![\w./-]*\.\w))(?:\.?/)?[\w.-]+/[\w./-]+")
_FILE_NOUN_RE = re.compile(_W + r"(?:files?|документ(?:и|ів|а)?|documents?|dockerfile|makefile|readme|changelog|license|notebook|spreadsheet|"
                           r"файл(?:и|ів|у|а|ом)?|директорі\w*|теку|тека|папк\w*|directory|directories|folders?|дир\w*)\b", _I)
_PERSIST_RE = re.compile(_W + r"(?:save|saved|store|persist|write (?:it |them |this )?(?:to|into|out to)|commit(?: it| them| this)?|check in|"
                         r"on disk(?! (?:usage|space|util\w*|pressure|io|i/o))|to disk|onto disk|to the filesystem|in the repo(?:sitory)?|into the repo(?:sitory)?|in the workspace|under [\w./-]+/|"
                         r"збережи|збережіть|зберегти|зберігай|запиши (?:у|в|до) файл\w*|на диск\w*|у репозиторі\w*|в репозиторі\w*|до репозиторі\w*|закоміть|закомітити|"
                         r"у файл\w*|в файл\w*|до файл\w*|у теку|в теку|у папку|в папку)\b", _I)
# an environment the request would change: config, service, cluster, repo, DB, ticket, branch, access …
_ENV_NOUN_RE = re.compile(_W + r"(?:config(?:s|uration|urations)?|settings?|setting|setup|firewall|iptables|dns|certificates?|certs?|secrets?|credentials?|tokens?|"
                          r"permissions?|roles?|access|acl|policy|policies|quota|limits?|flags?|feature[- ]flags?|env(?:ironment)? var(?:iable)?s?|variables?|"
                          r"branch(?:es)?|tags?|remote|repository|repo|upstream|fork|merge request|pull request|prs?|mrs?|"
                          r"database|db|schema|tables?|index(?:es)?|indices|columns?|rows?|records?|collection|bucket|queue|topic|cache|"
                          r"servers?|services?|cluster|nodes?|pods?|deployments?|replicas?|namespaces?|containers?|images?|volumes?|ingress|"
                          r"tickets?|issues?|jira|epics?|stor(?:y|ies)|cards?|boards?|alerts?|alarms?|monitors?|dashboards?|rules?|cron|jobs?|pipelines?|workflows?|schedules?|"
                          r"users?|accounts?|groups?|teams?|members?|webhooks?|integrations?|endpoints?|api|handler|handlers|module|modules|function|functions|class|classes|"
                          r"logic|code|codebase|source|tests?|test suite|dependenc(?:y|ies)|packages?|versions?|version|retry|timeout|threshold|"
                          r"конфіг\w*|налаштуванн\w*|параметр\w*|фаєрвол\w*|сертифікат\w*|секрет\w*|токен\w*|права|доступ\w*|політик\w*|ліміт\w*|прапор\w*|змінн\w*|"
                          r"гілк\w*|тег\w*|репозиторі\w*|реп[оа]\b|пул[- ]?реквест\w*|мердж[- ]?реквест\w*|"
                          r"баз\w* даних|бд|схем\w*|таблиц\w*|індекс\w*|колон\w*|запис\w*|бакет\w*|черг\w*|кеш\w*|"
                          r"сервер\w*|сервіс\w*|кластер\w*|вузл\w*|под\w*|деплой\w*|деплоймент\w*|реплік\w*|неймспейс\w*|контейнер\w*|образ\w*|"
                          r"тікет\w*|тикет\w*|задач\w*|джир\w*|алерт\w*|правил\w*|крон\w*|джоб\w*|пайплайн\w*|розклад\w*|"
                          r"користувач\w*|акаунт\w*|обліков\w*|груп\w*|вебхук\w*|інтеграці\w*|ендпоінт\w*|обробник\w*|модул\w*|функці\w*|клас\w*|логік\w*|код\w*|тест\w*|залежност\w*|пакет\w*|версі\w*|"
                          r"production|prod|staging|live|у проді|на проді|прод\w*|стейдж\w*)\b", _I)
# the result is text in the answer: "as an example", "in the reply", "I should run", "let me review", "preview", "as text", "текстом"
_REPLY_MEDIUM_RE = re.compile(_W + r"(?:in (?:the |your |this )?(?:reply|answer|response|chat|message|comment)|as (?:plain |raw )?text|as a (?:text|string)|"
                              r"(?:only |just )?(?:in|within) this (?:reply|answer|response|thread|conversation)|for me(?: to (?:review|read|look at|check|paste|copy))?|for us|"
                              r"here(?= *(?:[.,;:!]|$|\s+(?:and|but|so|then|as|in|with|for)\b))|inline|in[- ]line|for explanation|for illustration|"
                              r"as an? (?:example|illustration|sample|draft|proposal|suggestion)|for (?:my |our )?(?:review|reference|information|me to review)|"
                              r"(?:let|so) (?:me|us) (?:review|check|see|read|look|vet|approve)|i(?:'ll| will| can| would| should| could) (?:review|run|execute|apply|paste|copy|use|look)|"
                              r"(?:i|we) (?:should|would|could|can|will|might) (?:run|execute|apply|copy|paste|use)|you would (?:run|use|execute|type)|"
                              r"preview(?!\s+(?:namespace|environment|env|cluster|branch|deployment|url|link|server|build|release|site|stack|tenant|pod|host|instance|channel))|dry[- ]run (?:only|output)|show me|give me|print(?: out)?|output (?:it|them)|to copy|i (?:can|could) copy|копіювати|"
                              r"текстом|у відповіді|в відповіді|у чаті|в чаті|як приклад|для прикладу|для перегляду|на перегляд|щоб я (?:переглянув|перевірив|міг|могла|міг переглянути)|"
                              r"я (?:сам|сама)? ?(?:запущу|виконаю|застосую|перевірю|скопіюю)|без збереження|не зберіга\w+|not (?:save|saving|persist|persisting|writ\w+ (?:it |them )?to (?:a |the )?file|commit\w*|apply\w*|run\w*|execut\w*)|"
                              r"without (?:saving|persisting|writing (?:it |them )?(?:to|out)|committing|applying|running|executing|touching|changing|modifying)|"
                              r"instead of (?:saving|committing|applying|running|executing|changing)|rather than (?:saving|committing|applying|running|executing))\b", _I)
# text artefacts whose medium is ambiguous when nothing else is said
_TEXT_ARTEFACT_RE = re.compile(_W + r"(?:scripts?|patch(?:es)?|diffs?|sql|quer(?:y|ies)|statements?|commands?|snippets?|functions?|classes?|modules?|tests?|"
                               r"migrations?|configs?|configuration|manifests?|playbooks?|pipelines?|workflows?|dockerfile|compose file|code|implementation|fix|"
                               r"скрипт\w*|патч\w*|дифф?\w*|запит\w*|команд\w*|фрагмент\w*|функці\w*|клас\w*|модул\w*|тест\w*|міграці\w*|конфіг\w*|маніфест\w*|код\w*|реалізаці\w*|виправленн\w*)\b", _I)
_PRONOUN_OBJECT_RE = re.compile(r"^\s*(?:it|them|this|that|these|those|one|його|її|їх|це|цей|ці|той|ті|них|ними)\b", _I)
_GENERIC_CHANGE_RE = re.compile(_W + r"(?:anything|everything|nothing|something|any changes?|changes?|edits?|modifications?|writes?|"
                                r"нічого|щось|будь-що|все|усе|зміни|змін|правки|правок|редагуван\w*)\b", _I)
_ARTICLE_RE = re.compile(r"(?:(?:the|a|an|this|that|these|those|all|any|some|my|our|your|its)\s+)+", _I)
_UNIVERSAL_CHANGE_RE = re.compile(r"\s*(?:anything|everything|nothing|something|any changes?|нічого|щось|будь-що|все|усе)\b", _I)
_CONFIG_NOUN_RE = re.compile(r"(?:config(?:s|uration|urations)?|settings?|setup)$", _I)
_APPROVAL_RE = pv._APPROVAL_RE
# write-to-disk nominals inside a prohibition (sheet v5 rule 24): "no writes to disk", "all file writes are forbidden", "no file output"
_WRITE_NOMINAL_RE = re.compile(_W + r"(?:writes?|writing|written|file writes?|disk writes?|file output|output files?|persist\w*|sav(?:e|ed|es|ing))\b", _I)
_DISK_NOUN_RE = re.compile(_W + r"(?:disk|files?|file ?system|artifacts?|artefacts?|storage|working tree|workspace|repo(?:sitory)?|anything|everything|at all)\b", _I)
_REPO_NOUN_RE = re.compile(_W + r"(?:repo(?:sitory)?|working tree|workspace|git)\b", _I)
# "make the schema adjustment", "apply the performance correction we discussed" — a generic change noun as the object head, possibly with
# modifiers in front of it: what is changed, and where, is not established (sheet v5 3.3a; DCE-G1R3D)
_GENERIC_HEAD_RE = re.compile(r"(?:(?:[\w'’-]+\s+){0,3}?)(?P<head>changes?|edits?|modifications?|adjustments?|corrections?|tweaks?|fix(?:es)?|hotfix(?:es)?|amendments?|"
                              r"updates?|improvements?|refactor(?:ing|s)?|rework|cleanup|workarounds?|alterations?)\b(?!\s*(?:log|set|request|history|list|management|control|window|freeze|review|ticket|summary|description|plan))", _I)


@dataclass(frozen=True)
class EffectEvidence:
    kind: str                     # destination | environment | reply_medium | execution | removal | artefact_noun | pronoun_object |
                                  # no_object | inform_class | prohibition_medium | protected_overlap | unresolved
    text: str
    source: str                   # node id the text came from (objective, constraint, unresolved)
    span: Optional[Span] = None


@dataclass(frozen=True)
class EffectIntent:
    node_id: str                  # objective id, or an unresolved id for a clause the parser could not read as an action
    action: Optional[str]
    effect: str                   # one of the five classes
    conditional: bool
    approval_required: bool
    condition_ids: list[str]
    constraint_ids: list[str]
    evidence: list[EffectEvidence]
    source_span: Span
    reasons: list[str]


@dataclass(frozen=True)
class ProhibitedEffect:
    effect: str                   # one of the three side-effect classes
    constraint_id: str
    target_action: Optional[str]
    breadth: Optional[str]
    deferred_by: list[str]        # condition ids (e.g. "until approval") — a deferred prohibition is still a prohibition now
    approval_required: bool


@dataclass(frozen=True)
class EffectProjection:
    parser_version: str
    projection_version: str
    digest: str
    status: str
    intents: list[EffectIntent]
    prohibited_effects: list[ProhibitedEffect]
    unbound_restriction_ids: list[str]
    approval_gate_ids: list[str]
    side_effect_requested: bool   # any intent in SIDE_EFFECT_CLASSES (conditional ones count)
    unknown_count: int

    def to_dict(self) -> dict:
        return asdict(self)

    def intents_for(self, node_id: str) -> list[EffectIntent]:
        return [i for i in self.intents if i.node_id == node_id]


# --- helpers --------------------------------------------------------------------------------------------------------

def _ev(kind: str, m: Optional[re.Match], source: str, base: int = 0, text: Optional[str] = None) -> EffectEvidence:
    if m is not None:
        return EffectEvidence(kind, m.group(0), source, Span(base + m.start(), base + m.end()))
    return EffectEvidence(kind, text or "", source, None)


def _constraints_applying(ir: RequestIR, oid: str) -> list[Constraint]:
    return [c for c in ir.graph.constraints if c.scope == "request" or oid in c.applies_to_objective_ids]


def _adjacent_unresolved(ir: RequestIR, o: Objective) -> list[Unresolved]:
    """Unresolved clauses that follow the objective before the next objective starts (same sentence region)."""
    nxt = min((p.source_span.start for p in ir.graph.objectives if p.source_span.start > o.source_span.end), default=None)
    out = []
    for u in ir.graph.unresolved:
        if u.source_span.start >= o.source_span.end and (nxt is None or u.source_span.start < nxt) and u.source_span.start - o.source_span.end <= 120:
            out.append(u)
    return out


def _inside_protected(ir: RequestIR, span: Span) -> bool:
    return any(p.source_span.start <= span.start and span.end <= p.source_span.end for p in ir.graph.protected_regions)


_CONFIG_FILE_RE = re.compile(r"config|settings|values|secrets?|\.env\b|firewall|policy", _I)
_CONFIG_EXT_RE = re.compile(r"\.(?:ya?ml|json|toml|ini|cfg|conf|properties|env|tf|hcl)$", _I)
# a purpose / relative clause inside an object phrase: what follows describes the artefact's content, not where it goes
_PURPOSE_RE = re.compile(r"\s(?:for|to|that|which|who|so that|in order to|about|regarding|concerning|для|щоб|аби|що|який|яка|яке|які|котрий|котра|котрі|щодо|про|стосовно)\s", _I)
# a that-clause object: "write that everything is fine", "напиши, що все гаразд" — the deliverable is a statement in the reply
_THAT_CLAUSE_RE = re.compile(r"^\s*,?\s*(?:that|whether|how|why|what|which|що|чи|як|чому|скільки)\b", _I)


_SUBJECT_PURPOSE_RE = re.compile(r"\s(?:for|about|regarding|concerning|against|covering|describing|of|on)\s", _I)
_CODE_FILE_RE = re.compile(r"(?:[\w.-]+/)*[\w.-]+\.(?:py|js|ts|tsx|jsx|go|rs|java|kt|rb|php|c|h|cpp|cs|swift|scala|sql|sh|bash)\b", _I)
_LOCATIVE_RE = re.compile(r"\s(?:to|into|at|in|under|inside|onto|within)\s", _I)


def _in_subject_phrase(text: str, pos: int) -> bool:
    """True when ``text[pos]`` lies inside a non-locative purpose phrase ("… for <X>") with no locative preposition between the
    purpose marker and ``pos`` — the file there is what the artefact is *about*, not where it goes."""
    m = _SUBJECT_PURPOSE_RE.search(text)
    if m is None or m.end() > pos:
        return False
    locs = list(_LOCATIVE_RE.finditer(text, m.end(), pos))
    if not locs:
        return True
    loc = locs[-1]                                     # the preposition that governs the file is the one right before it
    # "a diff for the change to the retry logic in client.py" — "in <source file>" inside a purpose phrase still locates the *subject*
    # (where the logic lives), not where the artefact goes (DCE-G1R3D; a doc / data file after "in" stays a destination)
    return loc.group(0).strip().lower() in ("in", "inside", "within") and _CODE_FILE_RE.match(text, pos) is not None


def _destination(text: str, source: str, base: int) -> tuple[Optional[str], list[EffectEvidence]]:
    """Grounded persisted destination inside an object phrase → ``artifact_write`` (a configuration file such as
    ``config.yaml`` counts as ``environment_mutation``: editing it changes the running system). ``(None, [])`` when absent.

    Persist verbs and file nouns count only in the **head** of the phrase — before a purpose / relative clause ("a script for
    cleaning temp files", "скрипт для очищення файлів", "a job that writes to disk" describe content, not a destination)."""
    ev: list[EffectEvidence] = []
    ext = _FILE_EXT_RE.search(text)
    # "a patch for src/api.py", "a fix for the regression in …" — a file named inside a non-locative purpose phrase is the *subject*
    # of the artefact, not its destination (sheet v4 rule 18); "a note at docs/runbook.md", "the summary to docs/x.md" keep it
    if ext and _in_subject_phrase(text, ext.start()):
        ext = None
    path = _PATH_RE.search(text)
    if path and _in_subject_phrase(text, path.start()):
        path = None
    if ext and (_CONFIG_FILE_RE.search(ext.group(0)) or (_ENV_NOUN_RE.search(text[:ext.start()]) and _CONFIG_EXT_RE.search(ext.group(0)))):
        ev.append(_ev("environment", ext, source, base))               # "config.yaml", "конфігурацію пошуку в search.yaml"
        return ENVIRONMENT_MUTATION, ev
    pm = _PURPOSE_RE.search(text)
    head = text[:pm.start()] if pm else text
    hits = [m for m in (_PERSIST_RE.search(head), path, ext, _FILE_NOUN_RE.search(head)) if m]
    if hits:
        for m in hits:
            ev.append(_ev("destination", m, source, base))
        return ARTIFACT_WRITE, ev
    return None, ev


def _classify_object(text: str, source: str, base: int, action: str = "modify") -> tuple[Optional[str], list[EffectEvidence]]:
    """Positive evidence inside an object phrase.

    * a grounded destination → ``artifact_write`` (config file → ``environment_mutation``)
    * ``create``: when the first classifiable noun is a text artefact (script, patch, function, migration, config …) the
      medium is **not** established → ``None`` (caller emits ``unknown``); an environment noun first → ``environment_mutation``
    * ``modify`` / ``remove``: any environment noun (the thing already exists somewhere) → ``environment_mutation``
    """
    ev: list[EffectEvidence] = []
    off = len(text) - len(text.lstrip())
    am = _ARTICLE_RE.match(text, off)
    gen = _GENERIC_CHANGE_RE.match(text, am.end() if am else off)      # generic change noun as the object *head* only
    kind, ev2 = _destination(text, source, base)
    if action in ("modify", "create") and gen is not None and kind is None:
        # "make the change (to the config)", "apply the fix", "prepare the changes" — a generic change noun as the object head with no
        # persisted destination: the medium is not established → unknown (sheet v4 rule 18 / 3.3a; DCE-G1R3C). Universal objects
        # ("anything", "nothing", "everything") keep the environment reading for prohibitions and scope statements.
        if _UNIVERSAL_CHANGE_RE.match(gen.group(0)):
            ev.append(_ev("environment", gen, source, base))
            return ENVIRONMENT_MUTATION, ev
        ev.append(_ev("ambiguous_medium", gen, source, base))
        return None, ev
    if action in ("modify", "create") and kind is None and gen is None:
        gh = _GENERIC_HEAD_RE.match(text, am.end() if am else off)      # "the schema adjustment described in the runbook" → medium unknown
        if gh is not None and not _UNIVERSAL_CHANGE_RE.match(gh.group("head")):
            ev.append(_ev("ambiguous_medium", gh, source, base))
            return None, ev
    if kind is not None:
        return kind, ev + ev2
    pm = _PURPOSE_RE.search(text)
    head = text[:pm.start()] if pm else text                           # "the docs for the new retry setting" — the docs, not the setting
    env = _ENV_NOUN_RE.search(head)
    art = _TEXT_ARTEFACT_RE.search(head)
    if action == "create":
        if art and (env is None or art.start() <= env.start()):
            ev.append(_ev("artefact_noun", art, source, base))
            return None, ev
        if env and _CONFIG_NOUN_RE.match(env.group(0).strip()):          # "prepare / draft a config" with no destination → medium unknown (sheet v4 3.3a)
            ev.append(_ev("ambiguous_medium", env, source, base))
            return None, ev
    if env:
        ev.append(_ev("environment", env, source, base))
        return ENVIRONMENT_MUTATION, ev
    if art:
        ev.append(_ev("artefact_noun", art, source, base))
    return None, ev


def _reply_medium(ir: RequestIR, o: Objective, applying: list[Constraint]) -> tuple[list[EffectEvidence], list[EffectEvidence]]:
    """Evidence that the artefact is to be delivered in the answer, as ``(strong, weak)``.

    *strong* — the text names the medium or forbids persisting the artefact: "in the reply", "as text", "текстом", "as an example",
    "let me review it", "I should run", "preview", a prohibition on saving/committing/changing *it*/a file/disk, a format shape.
    *weak*   — a prohibition on **running/applying** the artefact ("but do not run them"): it fixes the medium only when no
    destination says otherwise ("create deploy.sh but do not run it" still writes the file).
    """
    strong: list[EffectEvidence] = []
    weak: list[EffectEvidence] = []
    base = o.source_span.start
    m = _REPLY_MEDIUM_RE.search(o.text)
    if m:
        strong.append(_ev("reply_medium", m, o.id, base))
    if o.output_shape is not None:
        strong.append(EffectEvidence("reply_medium", o.output_shape.text, o.id, o.output_shape.source_span))
    for c in applying:
        if c.kind == "format":
            strong.append(EffectEvidence("reply_medium", c.text, c.id, c.source_span))
            continue
        if c.kind in ("requirement", "scope_only") and _REPLY_MEDIUM_RE.search(c.text) and c.source_span.start >= o.source_span.start:
            strong.append(EffectEvidence("reply_medium", c.text, c.id, c.source_span))      # "but keep it only in this reply" (sheet v5 rule 21)
            continue
        if c.kind not in ("prohibition", "exclusion") or c.source_span.start < o.source_span.start - 2:
            continue
        obj = c.target_object.text if c.target_object else ""
        about_it = (c.target_object is None or _PRONOUN_OBJECT_RE.match(obj) is not None or _FILE_NOUN_RE.search(obj) is not None
                    or _PERSIST_RE.search(obj) is not None or (o.target is not None and _shares_head(o.target.text, obj)))
        if c.target_action in ("create", "modify") and about_it:                 # "do not save it to a file", "without committing"
            strong.append(EffectEvidence("prohibition_medium", c.text, c.id, c.source_span))
        elif c.target_action == "run" and about_it:                               # "but do not run them" / "не запускай їх"
            weak.append(EffectEvidence("prohibition_medium", c.text, c.id, c.source_span))
        elif c.target_action is None and c.target_object is not None and (_PERSIST_RE.search(obj) or re.search(_W + r"writes?|запис", obj, _I)):
            strong.append(EffectEvidence("prohibition_medium", c.text, c.id, c.source_span))   # "I forbid any write to disk"
    for u in _adjacent_unresolved(ir, o):
        um = _REPLY_MEDIUM_RE.search(u.text)
        if um:
            strong.append(_ev("reply_medium", um, u.id, u.source_span.start))
    return strong, weak


def _shares_head(a: str, b: str) -> bool:
    ta = {t for t in re.findall(r"[^\W\d_]{3,}", a.casefold())}
    tb = {t for t in re.findall(r"[^\W\d_]{3,}", b.casefold())}
    return bool(ta & tb)


def _gates(ir: RequestIR, node_id: str) -> tuple[list[str], bool, bool]:
    conds = pv.conditions_for(ir, node_id)
    ids = [q.id for q in conds]
    approval = any(_APPROVAL_RE.search(q.text) for q in conds)
    return ids, bool(conds), approval


# --- projection -----------------------------------------------------------------------------------------------------

def _project_objective(ir: RequestIR, o: Objective) -> EffectIntent:
    cls = ACTION_CLASS[o.action]
    applying = _constraints_applying(ir, o.id)
    cond_ids, conditional, approval = _gates(ir, o.id)
    reasons: list[str] = []
    ev: list[EffectEvidence] = []
    if _inside_protected(ir, o.source_span):
        reasons.append("objective_inside_protected_region")
        return EffectIntent(o.id, o.action, UNKNOWN, conditional, approval, cond_ids, [c.id for c in applying],
                            [EffectEvidence("protected_overlap", o.text, o.id, o.source_span)], o.source_span, reasons)
    if any(r.status == "unresolved" for r in o.references) and o.target is not None and _PRONOUN_OBJECT_RE.match(o.target.text):
        reasons.append("head_referent_unresolved")
        return EffectIntent(o.id, o.action, UNKNOWN, conditional, approval, cond_ids, [c.id for c in applying],
                            [EffectEvidence("pronoun_object", o.target.text, o.id, o.target.source_span)], o.source_span, reasons)

    if cls in ("inform", "judge", "propose"):
        ev.append(EffectEvidence("inform_class", o.action, o.id, o.trigger.source_span if o.trigger else o.source_span))
        return EffectIntent(o.id, o.action, REPLY_ONLY, conditional, approval, cond_ids, [c.id for c in applying], ev, o.source_span, ["inform_class"])

    if o.action == "run":
        ev.append(EffectEvidence("execution", o.trigger.text if o.trigger else o.text, o.id, o.trigger.source_span if o.trigger else o.source_span))
        return EffectIntent(o.id, o.action, COMMAND_EXECUTION, conditional, approval, cond_ids, [c.id for c in applying], ev, o.source_span, ["execute_class"])

    if o.action == "remove":
        ev.append(EffectEvidence("removal", o.trigger.text if o.trigger else o.text, o.id, o.trigger.source_span if o.trigger else o.source_span))
        if o.target is None:
            reasons.append("removal_without_object")
            return EffectIntent(o.id, o.action, UNKNOWN, conditional, approval, cond_ids, [c.id for c in applying], ev, o.source_span, reasons)
        if _PRONOUN_OBJECT_RE.match(o.target.text) and any(r.status == "unresolved" for r in o.references):
            reasons.append("removal_of_unresolved_pronoun")
            return EffectIntent(o.id, o.action, UNKNOWN, conditional, approval, cond_ids, [c.id for c in applying], ev, o.source_span, reasons)
        kind, obj_ev = _classify_object(o.target.text, o.id, o.target.source_span.start, "remove")
        ev.extend(obj_ev)
        return EffectIntent(o.id, o.action, ARTIFACT_WRITE if kind == ARTIFACT_WRITE else ENVIRONMENT_MUTATION, conditional, approval, cond_ids,
                            [c.id for c in applying], ev, o.source_span, ["remove_class", f"object:{kind or 'unclassified'}"])

    # create / modify: the medium decides
    target = o.target.text if o.target is not None else ""
    base = o.target.source_span.start if o.target is not None else o.source_span.start
    cids = [c.id for c in applying]
    strong_reply, weak_reply = _reply_medium(ir, o, applying)
    if target and _THAT_CLAUSE_RE.match(target):
        strong_reply = strong_reply + [EffectEvidence("reply_medium", target.split()[0].strip(","), o.id, o.target.source_span)]
    dest_kind, dest_ev = _destination(target, o.id, base) if target else (None, [])
    gen = _GENERIC_CHANGE_RE.search(target) if target else None
    bare_place = o.action == "modify" and bool(target) and not _PERSIST_RE.sub("", target).strip(" .,;:—-")   # "внеси зміни у репозиторій": verb carries the change, object is the place
    if dest_kind == ARTIFACT_WRITE and (gen or bare_place) and not (_FILE_EXT_RE.search(target) or _PATH_RE.search(target) or _FILE_NOUN_RE.search(target)):
        dest_kind = ENVIRONMENT_MUTATION                              # "make the changes in the repository" — the repository changes, no file is named
        if gen:
            dest_ev = [EffectEvidence("environment", gen.group(0), o.id, Span(base + gen.start(), base + gen.end()))] + dest_ev
    if dest_kind is not None:
        ev.extend(dest_ev)
        if strong_reply:                                             # "save it under docs/ … as an example" → contradictory medium
            ev.extend(strong_reply)
            reasons.append("medium_conflict")
            return EffectIntent(o.id, o.action, UNKNOWN, conditional, approval, cond_ids, cids, ev, o.source_span, reasons)
        return EffectIntent(o.id, o.action, dest_kind, conditional, approval, cond_ids, cids, ev, o.source_span, [f"destination:{dest_kind}"])
    if strong_reply or weak_reply:                                   # no destination and the text puts the artefact in the answer
        ev.extend(strong_reply + weak_reply)
        return EffectIntent(o.id, o.action, REPLY_ONLY, conditional, approval, cond_ids, cids, ev, o.source_span, ["reply_medium"])
    if not target:
        reasons.append("no_object")
        return EffectIntent(o.id, o.action, UNKNOWN, conditional, approval, cond_ids, cids, ev, o.source_span, reasons)
    if _PRONOUN_OBJECT_RE.match(target):
        reasons.append("pronoun_object")
        ev.append(EffectEvidence("pronoun_object", target, o.id, o.target.source_span))
        return EffectIntent(o.id, o.action, UNKNOWN, conditional, approval, cond_ids, cids, ev, o.source_span, reasons)
    kind, obj_ev = _classify_object(target, o.id, base, o.action)
    ev.extend(obj_ev)
    if kind is not None:
        return EffectIntent(o.id, o.action, kind, conditional, approval, cond_ids, cids, ev, o.source_span, [f"object:{kind}"])
    reasons.append("text_artefact_without_medium" if any(e.kind == "artefact_noun" for e in obj_ev) else "medium_not_established")
    return EffectIntent(o.id, o.action, UNKNOWN, conditional, approval, cond_ids, cids, ev, o.source_span, reasons)


def _project_unresolved(ir: RequestIR, u: Unresolved) -> Optional[EffectIntent]:
    if u.kind == "no_recognized_action":
        reason = "no_recognized_action"
    elif u.kind == "ambiguous_referent" and u.rule.endswith(".referent.do_pronoun"):
        reason = "pronoun_operation"                                    # "Do it." — an operation named only by a pronoun
    else:
        return None
    cond_ids, conditional, approval = _gates(ir, u.id)
    return EffectIntent(u.id, None, UNKNOWN, conditional, approval, cond_ids, [], [EffectEvidence("unresolved", u.text, u.id, u.source_span)],
                        u.source_span, [reason])


_PUBLISH_VERB_RE = re.compile(_W + r"(?:publish\w*|post\w*|send\w*|submit\w*|e-?mail\w*|upload\w*|push\w*|force[- ]?push\w*|merge\w*|rebas\w*|cherry[- ]?pick\w*|squash\w*|amend\w*|tag\w*|commit(?:s|ted|ting)?\b|опублік\w*|надішл\w*|надісла\w*|надсила\w*|відправ\w*|відішл\w*|запост\w*|залий|залива\w*|завантаж\w*|запуш\w*|пуш\w*|змерж\w*|мерж\w*|злий|злива\w*|перебаз\w*|ребейз\w*)\b", _I)


_COORD_PROHIBITION_RE = re.compile(r"\b(?:or|and|nor)\s+(?P<v>chang\w*|modif\w*|edit\w*|alter\w*|touch\w*|delet\w*|remov\w*|drop\w*|creat\w*|writ\w*|sav\w*|persist\w*|"
                                   r"run\w*|execut\w*|deploy\w*|restart\w*|install\w*|push\w*|commit\w*|merg\w*|send\w*|post\w*|publish\w*|open\w*)\s+(?P<o>[^,;.!?]{1,60})", _I)
_COORD_VERB_ACTION = {"chang": "modify", "modif": "modify", "edit": "modify", "alter": "modify", "touch": "modify", "delet": "remove", "remov": "remove", "drop": "remove",
                      "creat": "create", "writ": "create", "sav": "create", "persist": "create", "run": "run", "execut": "run", "deploy": "run", "restart": "run",
                      "install": "run", "push": "run", "commit": "run", "merg": "run", "send": "run", "post": "run", "publish": "run", "open": "create"}
_DOCUMENT_NOUN_RE = re.compile(_W + r"(?:reports?|bundles?|documents?|docs?|notes?|spreadsheets?|sheets?|notebooks?|datasets?|exports?|archives?|artefacts?|artifacts?|assets?|generated \w+|fixtures?|snapshots?|goldens?|"
                               r"snapshots?|dumps?|backups?|fixtures?|readme|markdown|csv|json|yaml|xlsx|pdf|slides?|decks?|workbooks?|ledgers?|logs?|attachments?)\b", _I)
_NULL_OBJECT_ANY_RE = re.compile(r"^\s*(?:anything|anything at all|anything whatsoever|a thing|a single thing|nothing)\b", _I)


_NOUN_LIST_RE = re.compile(r"\w+\s*,\s*\w+[^;]*?\b(?:or|and)\b|\w+\s+(?:or|and)\s+\w+", _I)


def _prohibited_classes(c: Constraint) -> list[str]:
    """Which effect classes a prohibition/exclusion forbids, from its action and object — the union over every coordinated
    verb phrase inside the prohibition ("Do not run anything or change environments" forbids execution *and* environment state;
    DCE-G1R3D, conservative union / no narrowing)."""
    out = list(_prohibited_classes_one(c))
    obj = c.target_object.text if c.target_object is not None else ""
    if c.kind == "prohibition" and c.target_action in ("modify", "create", "remove", None) and _NOUN_LIST_RE.search(obj):
        # "no tickets, commits, or file edits" — a nominal list unions the class of every item (DCE-G1R3D, conservative union)
        unbound = Constraint(c.id, c.kind, c.text, Span(c.source_span.start, c.source_span.end), c.rule, c.scope, list(c.applies_to_objective_ids),
                             target_action=None, value=None, target_object=c.target_object, breadth=c.breadth)
        out += [k for k in _prohibited_classes_one(unbound) if k not in out]
    for m in _COORD_PROHIBITION_RE.finditer(obj):
        stem = next((k for k in _COORD_VERB_ACTION if m.group("v").lower().startswith(k)), None)
        if stem is None:
            continue
        sub_obj = m.group("o").strip()
        sub = Constraint(c.id, c.kind, m.group(0), Span(c.source_span.start, c.source_span.end), c.rule, c.scope, list(c.applies_to_objective_ids),
                         target_action=_COORD_VERB_ACTION[stem], value=None, target_object=Mention(sub_obj, Span(c.source_span.start, c.source_span.end)),
                         breadth="global" if _NULL_OBJECT_ANY_RE.match(sub_obj) else "narrow")
        for k in _prohibited_classes_one(sub):
            if k not in out:
                out.append(k)
    return out


def _prohibited_classes_one(c: Constraint) -> list[str]:
    obj = c.target_object.text if c.target_object is not None else ""
    act = c.target_action
    if act == "run":
        verb = c.text if c.target_object is None else c.text[: max(0, c.target_object.source_span.start - c.source_span.start)] or c.text
        if _PUBLISH_VERB_RE.search(verb):                               # "do not merge the release branch" / "send nothing to Slack" — repository / service state
            return [ENVIRONMENT_MUTATION, COMMAND_EXECUTION]            # (sheet v3 rule 13; the execution class is kept as the conservative superset)
        if re.search(r"\bappl(?:y|ies|ying)\b", verb, _I):               # "do not apply it / the patch" — applying touches files and state as well (DCE-G1R3D)
            return [COMMAND_EXECUTION, ENVIRONMENT_MUTATION, ARTIFACT_WRITE]
        return [COMMAND_EXECUTION]
    if act == "remove":
        k, _ = _destination(obj, c.id, 0) if obj else (None, [])
        return [ARTIFACT_WRITE] if k == ARTIFACT_WRITE else [ENVIRONMENT_MUTATION]
    if act in ("create", "modify"):
        verb = c.text if c.target_object is None else c.text[: max(0, c.target_object.source_span.start - c.source_span.start)] or c.text
        if _PUBLISH_VERB_RE.search(verb):                               # "do not submit the pull request" — a service publication (DCE-G1R3D)
            return [ENVIRONMENT_MUTATION, COMMAND_EXECUTION]
        if re.search(_W + r"(?:network|remote|api|http|outbound|external)\s+(?:calls?|requests?)\b", obj, _I):
            return [COMMAND_EXECUTION, ENVIRONMENT_MUTATION]            # "make no network call" — a call reaches out and may change remote state
        if re.search(_W + r"(?:sav(?:e|ing)|persist\w*|stor(?:e|ing)|writ(?:e|ing)|export\w*|dump\w*)\b", verb, _I):
            return [ARTIFACT_WRITE]                                     # "Do not save or execute the triage helper" — the save is the artefact class
        if _REPO_NOUN_RE.search(obj) and c.rule.endswith(".keep_out_of"):
            return [ARTIFACT_WRITE, ENVIRONMENT_MUTATION]              # "keep it out of the repository"
        dest, _ = _destination(obj, c.id, 0) if obj else (None, [])
        if dest == ARTIFACT_WRITE and _GENERIC_CHANGE_RE.search(obj) and not (_FILE_EXT_RE.search(obj) or _FILE_NOUN_RE.search(obj)):
            return [ENVIRONMENT_MUTATION, ARTIFACT_WRITE]              # "не внось змін у репозиторій", "no changes in the repo"
        if dest == ARTIFACT_WRITE:                                      # "do not save it to a file", "no writes to disk"
            return [ARTIFACT_WRITE]
        # "No writes to disk", "Any writes to disk are prohibited", "All file writes are forbidden", "do not persist anything to disk",
        # "no file output" — a write-to-disk nominal forbids the artefact class whatever noun carries it (sheet v5 rule 24; DCE-G1R3D)
        if _WRITE_NOMINAL_RE.search(c.text) and (_DISK_NOUN_RE.search(c.text) or not obj):
            if _REPO_NOUN_RE.search(c.text):                            # "no writes to the repo / working tree" — repository state too
                return [ARTIFACT_WRITE, ENVIRONMENT_MUTATION]
            return [ARTIFACT_WRITE]
        if dest == ENVIRONMENT_MUTATION:                                # "don't edit config.yaml"
            return [ENVIRONMENT_MUTATION]
        env = _ENV_NOUN_RE.search(obj) if obj else None
        generic = not obj or c.breadth in ("global", None) or _GENERIC_CHANGE_RE.search(obj) is not None
        if env and (not generic or _GENERIC_CHANGE_RE.search(obj)):  # "не внось змін у репозиторій", "no production edits" → that environment
            return [ENVIRONMENT_MUTATION]
        if generic and c.breadth == "global" and _NULL_OBJECT_ANY_RE.match(obj) and act == "modify":
            return [ENVIRONMENT_MUTATION, ARTIFACT_WRITE, COMMAND_EXECUTION]   # "Do not change anything" — a universal state freeze (DCE-G1R3D; commands change state too)
        if generic:                                                     # "don't make changes", "touch nothing", "do not create anything"
            return [ENVIRONMENT_MUTATION, ARTIFACT_WRITE]
        if _PRONOUN_OBJECT_RE.match(obj):                               # "don't create it" — whatever it is, nothing persists
            return [ENVIRONMENT_MUTATION, ARTIFACT_WRITE]
        if _DOCUMENT_NOUN_RE.search(obj) and not env:                   # "The finance report must not be modified" — a document is an artefact (DCE-G1R3D)
            return [ARTIFACT_WRITE, ENVIRONMENT_MUTATION]
        return [ENVIRONMENT_MUTATION]                                   # a specific named thing ("the wiring", "stale branches")
    if act is None:
        # unbound: classify from the object only when it is unmistakable
        if not obj:
            return list(SIDE_EFFECT_CLASSES) if c.kind == "prohibition" and c.breadth == "global" else []
        out: list[str] = []                                             # DCE-G1R3D: a list object ("no tickets, commits, or file edits") unions every family
        if re.search(_W + r"(?:shell|scripts?|commands?|execut\w*|runs?|deploy\w*|restart\w*|install\w*|acting on|act on|network calls?|remote calls?|api calls?|команд\w*|скрипт\w*|запуск\w*|деплой\w*)\b", obj, _I):
            out.append(COMMAND_EXECUTION)
        if re.search(_W + r"(?:actions?|operations?|side[- ]effects?)\b", obj, _I) and not re.search(_W + r"(?:text|chat|reply|answer)\b", obj, _I):
            out += [COMMAND_EXECUTION, ENVIRONMENT_MUTATION]                # "No production actions" — an action acts on state and is executed
        if _PERSIST_RE.search(obj) or _FILE_NOUN_RE.search(obj) or re.search(_W + r"(?:writes?|outputs?|artifacts?|artefacts?|exports?|dumps?|запис\w*)\b", obj, _I):
            out.append(ARTIFACT_WRITE)
        if _ENV_NOUN_RE.search(obj) or re.search(_W + r"(?:edits?|commits?|changes?|modifications?|touch\w*|tickets?|issues?|merges?|pushes|deploys?|змін\w*|правк\w*)\b", obj, _I):
            out.append(ENVIRONMENT_MUTATION)
        return [k for k in SIDE_EFFECT_CLASSES if k in out]
    return []   # prohibitions on inform/judge/propose actions do not forbid a side-effect class


def project_effects(ir: RequestIR) -> EffectProjection:
    """Project every objective (and every unreadable operation clause) onto an effect class. Pure; deterministic."""
    intents: list[EffectIntent] = [_project_objective(ir, o) for o in ir.graph.objectives]
    for u in ir.graph.unresolved:
        pi = _project_unresolved(ir, u)
        if pi is not None:
            intents.append(pi)
    intents.sort(key=lambda i: i.source_span.start)
    prohibited: list[ProhibitedEffect] = []
    for c in ir.graph.constraints:
        if c.kind not in ("prohibition", "exclusion"):
            continue
        if c.kind == "exclusion" and c.target_action not in ("run", "remove", "create", "modify") and not _prohibited_classes(c):
            continue                                                     # "without acting on it" — an unbound exclusion that names a side-effect class still counts (DCE-G1R3D)
        conds = pv.conditions_for(ir, c.id)
        approval = any(_APPROVAL_RE.search(q.text) for q in conds)
        for eff in _prohibited_classes(c):
            prohibited.append(ProhibitedEffect(eff, c.id, c.target_action, c.breadth, [q.id for q in conds], approval))
    unbound = [c.id for c in pv.unbound_restrictions(ir)]
    gates = [g[0] for g in pv.approval_gates(ir)]
    return EffectProjection(ir.parser_version, PROJECTION_VERSION, ir.digest, ir.status, intents, prohibited, unbound, gates,
                            any(i.effect in SIDE_EFFECT_CLASSES for i in intents), sum(1 for i in intents if i.effect == UNKNOWN))


# --- policy boundary ---------------------------------------------------------------------------------------------------

def effect_policy(ir: RequestIR, effect: str, node_id: Optional[str] = None, projection: Optional[EffectProjection] = None) -> dict:
    """Deny-by-default, read-only reading of the text for one side-effect class (optionally one intent).

    Returns ``{"decision": DENY | REQUIRE_RESOLUTION | TEXT_NOT_PROHIBITED, "reasons": [...], "intents": [node ids]}``.
    There is no ALLOW: ``TEXT_NOT_PROHIBITED`` only says that the text contains a direct, unconditional, unambiguous request for
    this effect class and nothing in the text forbids or qualifies it. Authorization, environment permissions and explicit human
    approval are separate mechanisms outside this library; a consumer must bind this result to them and must never execute on it.

    Fail-closed rules: ``DENY`` when the class is prohibited by the text (including deferred "until approval" prohibitions), when
    the parser status is not ok/ok_with_unresolved, or when ``effect`` is ``unknown``/``reply_only`` asked as a side effect;
    ``REQUIRE_RESOLUTION`` on any of: unknown intents present, unbound restrictions, approval gates, unresolved nodes, conditional
    or approval-gated intents, the class not requested, a target that is a pronoun, or no traceable source span.
    """
    proj = projection if projection is not None else project_effects(ir)
    reasons: list[str] = []
    if effect not in SIDE_EFFECT_CLASSES:
        return {"decision": DENY, "reasons": [f"not_a_side_effect_class:{effect}"], "intents": []}
    if ir.status not in ("ok", "ok_with_unresolved"):
        reasons.append(f"status:{ir.status}")
    for p in proj.prohibited_effects:
        if p.effect == effect:
            reasons.append(f"prohibited:{p.constraint_id}" + (":deferred" if p.deferred_by else ""))
    if any(r.startswith("prohibited:") for r in reasons) or ir.status not in ("ok", "ok_with_unresolved"):
        return {"decision": DENY, "reasons": reasons, "intents": []}
    for cid in proj.unbound_restriction_ids:
        reasons.append(f"unbound_restriction:{cid}")
    for gid in proj.approval_gate_ids:
        reasons.append(f"approval_gate:{gid}")
    for u in ir.graph.unresolved:
        reasons.append(f"unresolved:{u.id}:{u.kind}")
    for i in proj.intents:
        if i.effect == UNKNOWN:
            reasons.append(f"unknown_effect:{i.node_id}")
    asks = [i for i in proj.intents if i.effect == effect and (node_id is None or i.node_id == node_id)]
    if not asks:
        reasons.append("not_requested")
    for i in asks:
        if i.conditional:
            reasons.append(f"conditional:{i.node_id}:" + ",".join(i.condition_ids))
        if i.approval_required:
            reasons.append(f"approval_required:{i.node_id}")
        if any(e.kind == "pronoun_object" for e in i.evidence):
            reasons.append(f"pronoun_target:{i.node_id}")
        if i.source_span.end <= i.source_span.start:
            reasons.append(f"untraceable_source:{i.node_id}")
    decision = REQUIRE_RESOLUTION if reasons else TEXT_NOT_PROHIBITED
    return {"decision": decision, "reasons": reasons, "intents": [i.node_id for i in asks]}
